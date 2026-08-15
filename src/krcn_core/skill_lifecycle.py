"""Deterministic, approval-gated skill learning lifecycle metadata.

This module never writes a skill or registry.  It validates content-free
candidate/evaluation records and prepares exact Mutation Gate plans for a
separate registry owner to review and apply.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from .information_records import canonical_json
from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/@-]*$")
STATES = {"candidate", "evaluated", "approval-required", "active", "deprecated", "retired"}
TERMINAL_STATES = {"deprecated", "retired"}
POLICY_INVARIANTS = {
    "candidate_self_promotion_allowed": False,
    "registry_write_performed": False,
    "skill_code_included": False,
    "skill_content_included": False,
    "physical_paths_included": False,
    "secret_values_included": False,
    "grants_authority": False,
}
PUBLIC_INVARIANTS = {
    "skill_code_included": False,
    "skill_content_included": False,
    "physical_paths_included": False,
    "secret_values_included": False,
    "grants_authority": False,
}


class SkillLifecycleError(ValueError):
    """Raised when learning evidence or a lifecycle transition is unsafe."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _strict(payload: object, expected: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SkillLifecycleError(f"{label} fields are invalid")
    return payload


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise SkillLifecycleError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise SkillLifecycleError(f"{label} must be a SHA-256 digest")
    return value


def _logical_ref(value: object, label: str) -> str:
    if isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in ("password=", "token=", "api-key=", "secret=")):
            raise SkillLifecycleError(f"{label} must not contain a secret")
        if "\\" in value or "://" in value:
            raise SkillLifecycleError(f"{label} must not contain a physical path")
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise SkillLifecycleError(f"{label} must be a logical reference")
    suffix = value.split(":", 1)[1]
    if ".." in suffix.split("/"):
        raise SkillLifecycleError(f"{label} must not contain a physical path")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SkillLifecycleError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise SkillLifecycleError(f"{label} is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise SkillLifecycleError(f"{label} must be UTC")
    return value


def _sorted_unique_digests(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SkillLifecycleError(f"{label} must be a list")
    items = tuple(_sha256(item, label) for item in value)
    if (not allow_empty and not items) or items != tuple(sorted(set(items))):
        raise SkillLifecycleError(f"{label} must be a sorted unique digest list")
    return items


def _sorted_unique_refs(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SkillLifecycleError(f"{label} must be a list")
    items = tuple(_logical_ref(item, label) for item in value)
    if not items or items != tuple(sorted(set(items))):
        raise SkillLifecycleError(f"{label} must be a sorted unique logical reference list")
    return items


@dataclass(frozen=True)
class SkillLifecyclePolicy:
    policy_revision: int
    minimum_trials: int
    pass_threshold_basis_points: int
    minimum_passed_trials: int
    maximum_candidates: int
    policy_digest: str


def load_skill_lifecycle_policy(repo_root: Path) -> SkillLifecyclePolicy:
    """Load the versioned policy without performing discovery or network I/O."""

    path = repo_root / "config" / "skill-lifecycle-policy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillLifecycleError("skill lifecycle policy is unreadable") from exc
    _strict(
        payload,
        {
            "schema_ref",
            "schema_version",
            "policy_revision",
            "minimum_trials",
            "minimum_passed_trials",
            "pass_threshold_basis_points",
            "maximum_candidates",
            "invariants",
        },
        "skill lifecycle policy",
    )
    if (
        payload.get("schema_ref") != "schemas/skill-lifecycle-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != POLICY_INVARIANTS
    ):
        raise SkillLifecycleError("skill lifecycle policy contract is invalid")
    values = {
        key: payload.get(key)
        for key in (
            "policy_revision",
            "minimum_trials",
            "minimum_passed_trials",
            "pass_threshold_basis_points",
            "maximum_candidates",
        )
    }
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values.values()):
        raise SkillLifecycleError("skill lifecycle policy limits are invalid")
    if (
        values["policy_revision"] < 1
        or not 1 <= values["minimum_trials"] <= 1000
        or not 1 <= values["minimum_passed_trials"] <= values["minimum_trials"]
        or not 1 <= values["pass_threshold_basis_points"] <= 10000
        or not 1 <= values["maximum_candidates"] <= 100000
    ):
        raise SkillLifecycleError("skill lifecycle policy limits are invalid")
    return SkillLifecyclePolicy(
        values["policy_revision"],
        values["minimum_trials"],
        values["pass_threshold_basis_points"],
        values["minimum_passed_trials"],
        values["maximum_candidates"],
        _digest(payload),
    )


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    skill_id: str
    proposed_by_ref: str
    proposer_identity_digest: str
    source_refs: tuple[str, ...]
    source_digest: str
    repetition_digests: tuple[str, ...]
    proposer_model_digest: str
    candidate_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/skill-candidate.schema.json",
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "skill_id": self.skill_id,
            "state": "candidate",
            "proposed_by_ref": self.proposed_by_ref,
            "proposer_identity_digest": self.proposer_identity_digest,
            "source_refs": list(self.source_refs),
            "source_digest": self.source_digest,
            "repetition_digests": list(self.repetition_digests),
            "proposer_model_digest": self.proposer_model_digest,
            "candidate_digest": self.candidate_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def skill_candidate_digest(
    candidate_id: str,
    skill_id: str,
    proposed_by_ref: str,
    proposer_identity_digest: str,
    source_refs: tuple[str, ...],
    source_digest: str,
    repetition_digests: tuple[str, ...],
    proposer_model_digest: str,
) -> str:
    return _digest(
        {
            "candidate_id": candidate_id,
            "skill_id": skill_id,
            "state": "candidate",
            "proposed_by_ref": proposed_by_ref,
            "proposer_identity_digest": proposer_identity_digest,
            "source_refs": list(source_refs),
            "source_digest": source_digest,
            "repetition_digests": list(repetition_digests),
            "proposer_model_digest": proposer_model_digest,
            "invariants": PUBLIC_INVARIANTS,
        }
    )


def build_skill_candidate(
    *,
    candidate_id: str,
    skill_id: str,
    proposed_by_ref: str,
    proposer_identity_digest: str,
    source_refs: Iterable[str],
    source_digest: str,
    repetition_digests: Iterable[str],
    proposer_model_digest: str,
) -> SkillCandidate:
    refs = tuple(sorted(set(source_refs)))
    repetitions = tuple(sorted(set(repetition_digests)))
    payload = {
        "schema_ref": "schemas/skill-candidate.schema.json",
        "schema_version": 1,
        "candidate_id": candidate_id,
        "skill_id": skill_id,
        "state": "candidate",
        "proposed_by_ref": proposed_by_ref,
        "proposer_identity_digest": proposer_identity_digest,
        "source_refs": list(refs),
        "source_digest": source_digest,
        "repetition_digests": list(repetitions),
        "proposer_model_digest": proposer_model_digest,
        "candidate_digest": skill_candidate_digest(
            candidate_id,
            skill_id,
            proposed_by_ref,
            proposer_identity_digest,
            refs,
            source_digest,
            repetitions,
            proposer_model_digest,
        ),
        "invariants": PUBLIC_INVARIANTS,
    }
    return parse_skill_candidate(payload)


def parse_skill_candidate(payload: object) -> SkillCandidate:
    expected = {
        "schema_ref", "schema_version", "candidate_id", "skill_id", "state",
        "proposed_by_ref", "proposer_identity_digest", "source_refs", "source_digest", "repetition_digests",
        "proposer_model_digest", "candidate_digest", "invariants",
    }
    data = _strict(payload, expected, "skill candidate")
    if (
        data.get("schema_ref") != "schemas/skill-candidate.schema.json"
        or data.get("schema_version") != 1
        or data.get("state") != "candidate"
        or data.get("invariants") != PUBLIC_INVARIANTS
    ):
        raise SkillLifecycleError("skill candidate contract is invalid")
    candidate_id = _identifier(data.get("candidate_id"), "candidate_id")
    skill_id = _identifier(data.get("skill_id"), "skill_id")
    proposed_by_ref = _logical_ref(data.get("proposed_by_ref"), "proposed_by_ref")
    proposer_identity_digest = _sha256(data.get("proposer_identity_digest"), "proposer_identity_digest")
    source_refs = _sorted_unique_refs(data.get("source_refs"), "source_refs")
    source_digest = _sha256(data.get("source_digest"), "source_digest")
    repetitions = _sorted_unique_digests(data.get("repetition_digests"), "repetition_digests")
    proposer_model_digest = _sha256(data.get("proposer_model_digest"), "proposer_model_digest")
    candidate_digest = _sha256(data.get("candidate_digest"), "candidate_digest")
    expected_digest = skill_candidate_digest(
        candidate_id, skill_id, proposed_by_ref, proposer_identity_digest, source_refs, source_digest,
        repetitions, proposer_model_digest,
    )
    if candidate_digest != expected_digest:
        raise SkillLifecycleError("skill candidate digest does not match")
    return SkillCandidate(
        candidate_id, skill_id, proposed_by_ref, proposer_identity_digest, source_refs, source_digest,
        repetitions, proposer_model_digest, candidate_digest,
    )


def find_skill_candidate_duplicates(candidates: Iterable[SkillCandidate]) -> tuple[dict[str, object], ...]:
    """Group candidates sharing a source digest or repetition evidence."""

    checked = [parse_skill_candidate(item.as_payload()) for item in candidates]
    if len({item.candidate_id for item in checked}) != len(checked):
        raise SkillLifecycleError("skill candidates contain duplicate identities")
    parent = {item.candidate_id: item.candidate_id for item in checked}

    def root(item_id: str) -> str:
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def union(left: str, right: str) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for index, left in enumerate(checked):
        for right in checked[index + 1:]:
            if left.source_digest == right.source_digest or set(left.repetition_digests) & set(right.repetition_digests):
                union(left.candidate_id, right.candidate_id)
    groups: dict[str, list[str]] = {}
    for item in checked:
        groups.setdefault(root(item.candidate_id), []).append(item.candidate_id)
    return tuple(
        {
            "canonical_candidate_id": sorted(ids)[0],
            "duplicate_candidate_ids": sorted(ids)[1:],
            "evidence_weight": 1,
        }
        for ids in sorted(groups.values(), key=lambda group: sorted(group)[0])
        if len(ids) > 1
    )


@dataclass(frozen=True)
class SkillEvaluation:
    evaluation_id: str
    candidate_id: str
    candidate_digest: str
    proposer_identity_digest: str
    project_fixture_digest: str
    evaluation_run_digest: str
    evaluator_ref: str
    verifier_ref: str
    evaluator_identity_digest: str
    verifier_identity_digest: str
    tested_model_digest: str
    verifier_model_digest: str
    environment_digest: str
    trial_count: int
    passed_trials: int
    score_basis_points: int
    outcome: str
    evaluated_at: str
    evaluation_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/skill-evaluation.schema.json",
            "schema_version": 1,
            "evaluation_id": self.evaluation_id,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "proposer_identity_digest": self.proposer_identity_digest,
            "state": "evaluated",
            "project_fixture_digest": self.project_fixture_digest,
            "evaluation_run_digest": self.evaluation_run_digest,
            "evaluator_ref": self.evaluator_ref,
            "verifier_ref": self.verifier_ref,
            "evaluator_identity_digest": self.evaluator_identity_digest,
            "verifier_identity_digest": self.verifier_identity_digest,
            "tested_model_digest": self.tested_model_digest,
            "verifier_model_digest": self.verifier_model_digest,
            "environment_digest": self.environment_digest,
            "trial_count": self.trial_count,
            "passed_trials": self.passed_trials,
            "score_basis_points": self.score_basis_points,
            "outcome": self.outcome,
            "evaluated_at": self.evaluated_at,
            "evaluation_digest": self.evaluation_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def _evaluation_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in payload if key not in {"schema_ref", "schema_version", "evaluation_digest"}}


def build_skill_evaluation(
    policy: SkillLifecyclePolicy,
    candidate: SkillCandidate,
    *,
    evaluation_id: str,
    project_fixture_digest: str,
    evaluation_run_digest: str,
    evaluator_ref: str,
    verifier_ref: str,
    evaluator_identity_digest: str,
    verifier_identity_digest: str,
    tested_model_digest: str,
    verifier_model_digest: str,
    environment_digest: str,
    trial_count: int,
    passed_trials: int,
    score_basis_points: int,
    evaluated_at: str,
) -> SkillEvaluation:
    candidate = parse_skill_candidate(candidate.as_payload())
    evaluator_identity_digest = _sha256(evaluator_identity_digest, "evaluator_identity_digest")
    verifier_identity_digest = _sha256(verifier_identity_digest, "verifier_identity_digest")
    if evaluator_ref == verifier_ref or evaluator_identity_digest == verifier_identity_digest:
        raise SkillLifecycleError("independent verifier identity is required")
    if candidate.proposer_identity_digest in {
        evaluator_identity_digest,
        verifier_identity_digest,
    }:
        raise SkillLifecycleError("proposer, evaluator, and verifier identities must be distinct")
    if tested_model_digest == verifier_model_digest:
        raise SkillLifecycleError("independent verifier model is required")
    outcome = "passed" if (
        trial_count >= policy.minimum_trials
        and passed_trials >= policy.minimum_passed_trials
        and (passed_trials * 10000) // trial_count >= policy.pass_threshold_basis_points
        and score_basis_points >= policy.pass_threshold_basis_points
    ) else "failed"
    payload: dict[str, object] = {
        "schema_ref": "schemas/skill-evaluation.schema.json",
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "candidate_id": candidate.candidate_id,
        "candidate_digest": candidate.candidate_digest,
        "proposer_identity_digest": candidate.proposer_identity_digest,
        "state": "evaluated",
        "project_fixture_digest": project_fixture_digest,
        "evaluation_run_digest": evaluation_run_digest,
        "evaluator_ref": evaluator_ref,
        "verifier_ref": verifier_ref,
        "evaluator_identity_digest": evaluator_identity_digest,
        "verifier_identity_digest": verifier_identity_digest,
        "tested_model_digest": tested_model_digest,
        "verifier_model_digest": verifier_model_digest,
        "environment_digest": environment_digest,
        "trial_count": trial_count,
        "passed_trials": passed_trials,
        "score_basis_points": score_basis_points,
        "outcome": outcome,
        "evaluated_at": evaluated_at,
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["evaluation_digest"] = _digest(_evaluation_identity(payload))
    return parse_skill_evaluation(payload)


def parse_skill_evaluation(payload: object) -> SkillEvaluation:
    expected = {
        "schema_ref", "schema_version", "evaluation_id", "candidate_id",
        "candidate_digest", "proposer_identity_digest", "state", "project_fixture_digest",
        "evaluation_run_digest", "evaluator_ref", "verifier_ref",
        "evaluator_identity_digest", "verifier_identity_digest",
        "tested_model_digest", "verifier_model_digest", "environment_digest",
        "trial_count", "passed_trials", "score_basis_points", "outcome",
        "evaluated_at", "evaluation_digest", "invariants",
    }
    data = _strict(payload, expected, "skill evaluation")
    if (
        data.get("schema_ref") != "schemas/skill-evaluation.schema.json"
        or data.get("schema_version") != 1
        or data.get("state") != "evaluated"
        or data.get("invariants") != PUBLIC_INVARIANTS
        or data.get("outcome") not in {"passed", "failed"}
    ):
        raise SkillLifecycleError("skill evaluation contract is invalid")
    evaluation_id = _identifier(data.get("evaluation_id"), "evaluation_id")
    candidate_id = _identifier(data.get("candidate_id"), "candidate_id")
    candidate_digest = _sha256(data.get("candidate_digest"), "candidate_digest")
    proposer_identity_digest = _sha256(data.get("proposer_identity_digest"), "proposer_identity_digest")
    digests = [
        _sha256(data.get(name), name)
        for name in (
            "project_fixture_digest", "evaluation_run_digest", "tested_model_digest",
            "verifier_model_digest", "environment_digest",
        )
    ]
    evaluator_ref = _logical_ref(data.get("evaluator_ref"), "evaluator_ref")
    verifier_ref = _logical_ref(data.get("verifier_ref"), "verifier_ref")
    evaluator_identity_digest = _sha256(data.get("evaluator_identity_digest"), "evaluator_identity_digest")
    verifier_identity_digest = _sha256(data.get("verifier_identity_digest"), "verifier_identity_digest")
    if evaluator_ref == verifier_ref or evaluator_identity_digest == verifier_identity_digest:
        raise SkillLifecycleError("independent verifier identity is required")
    if len({proposer_identity_digest, evaluator_identity_digest, verifier_identity_digest}) != 3:
        raise SkillLifecycleError("proposer, evaluator, and verifier identities must be distinct")
    if digests[2] == digests[3]:
        raise SkillLifecycleError("independent verifier model is required")
    trial_count = data.get("trial_count")
    passed_trials = data.get("passed_trials")
    score = data.get("score_basis_points")
    if (
        any(not isinstance(item, int) or isinstance(item, bool) for item in (trial_count, passed_trials, score))
        or not 1 <= trial_count <= 1000
        or not 0 <= passed_trials <= trial_count
        or not 0 <= score <= 10000
    ):
        raise SkillLifecycleError("skill evaluation measurements are invalid")
    evaluated_at = _timestamp(data.get("evaluated_at"), "evaluated_at")
    evaluation_digest = _sha256(data.get("evaluation_digest"), "evaluation_digest")
    if evaluation_digest != _digest(_evaluation_identity(data)):
        raise SkillLifecycleError("skill evaluation digest does not match")
    return SkillEvaluation(
        evaluation_id, candidate_id, candidate_digest, proposer_identity_digest,
        digests[0], digests[1],
        evaluator_ref, verifier_ref, evaluator_identity_digest,
        verifier_identity_digest, digests[2], digests[3], digests[4],
        trial_count, passed_trials, score, str(data["outcome"]), evaluated_at,
        evaluation_digest,
    )


@dataclass(frozen=True)
class SkillRegistryChangePlan:
    skill_id: str
    candidate_id: str
    candidate_digest: str
    evaluation_digest: str
    proposed_by_ref: str
    proposer_identity_digest: str
    evaluator_identity_digest: str
    verifier_identity_digest: str
    approver_identity_digest: str
    from_state: str
    to_state: str
    expected_registry_digest: str | None
    registry_record_digest: str
    rollback_target_ref: str
    supersedes_ref: str | None
    mutation: MutationPlan
    plan_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/skill-registry-change-plan.schema.json",
            "schema_version": 1,
            "skill_id": self.skill_id,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "evaluation_digest": self.evaluation_digest,
            "proposed_by_ref": self.proposed_by_ref,
            "proposer_identity_digest": self.proposer_identity_digest,
            "evaluator_identity_digest": self.evaluator_identity_digest,
            "verifier_identity_digest": self.verifier_identity_digest,
            "approver_identity_digest": self.approver_identity_digest,
            "state": "approval-required",
            "from_state": self.from_state,
            "to_state": self.to_state,
            "expected_registry_digest": self.expected_registry_digest,
            "registry_record_digest": self.registry_record_digest,
            "rollback_target_ref": self.rollback_target_ref,
            "supersedes_ref": self.supersedes_ref,
            "mutation": self.mutation.as_dict(),
            "plan_digest": self.plan_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def _registry_plan_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in payload if key not in {"schema_ref", "schema_version", "plan_digest"}}


def prepare_skill_activation(
    resolver: OwnershipResolver,
    policy: SkillLifecyclePolicy,
    candidate: SkillCandidate,
    evaluation: SkillEvaluation,
    *,
    expected_registry_digest: str | None,
    rollback_target_ref: str,
    approver_identity_digest: str,
    supersedes_ref: str | None = None,
) -> SkillRegistryChangePlan:
    """Prepare, but never apply, an exact registry mutation plan."""

    candidate = parse_skill_candidate(candidate.as_payload())
    evaluation = parse_skill_evaluation(evaluation.as_payload())
    if evaluation.candidate_id != candidate.candidate_id or evaluation.candidate_digest != candidate.candidate_digest:
        raise SkillLifecycleError("evaluation does not bind the candidate")
    if evaluation.proposer_identity_digest != candidate.proposer_identity_digest:
        raise SkillLifecycleError("evaluation proposer identity does not bind the candidate")
    if evaluation.outcome != "passed":
        raise SkillLifecycleError("failed evaluation cannot request approval")
    if (
        evaluation.trial_count < policy.minimum_trials
        or evaluation.passed_trials < policy.minimum_passed_trials
        or (evaluation.passed_trials * 10000) // evaluation.trial_count
        < policy.pass_threshold_basis_points
        or evaluation.score_basis_points < policy.pass_threshold_basis_points
    ):
        raise SkillLifecycleError("insufficient evaluation evidence")
    rollback = _logical_ref(rollback_target_ref, "rollback_target_ref")
    supersedes = None if supersedes_ref is None else _logical_ref(supersedes_ref, "supersedes_ref")
    approver_identity_digest = _sha256(approver_identity_digest, "approver_identity_digest")
    if len({
        candidate.proposer_identity_digest,
        evaluation.evaluator_identity_digest,
        evaluation.verifier_identity_digest,
        approver_identity_digest,
    }) != 4:
        raise SkillLifecycleError("proposer, evaluator, verifier, and approver identities must be distinct")
    previous = None if expected_registry_digest is None else _sha256(expected_registry_digest, "expected_registry_digest")
    registry_identity = {
        "skill_id": candidate.skill_id,
        "candidate_digest": candidate.candidate_digest,
        "evaluation_digest": evaluation.evaluation_digest,
        "state": "active",
        "rollback_target_ref": rollback,
        "supersedes_ref": supersedes,
        "expected_registry_digest": previous,
        "invariants": PUBLIC_INVARIANTS,
    }
    registry_digest = _digest(registry_identity)
    mutation = plan_mutation(
        resolver,
        operation="create" if previous is None else "update",
        target_ref=f".krcn/global/knowledge/skill-registry/{candidate.skill_id}.json",
        expected_ownership="user-data",
        change_digest=registry_digest,
        reversible=True,
    )
    payload: dict[str, object] = {
        "schema_ref": "schemas/skill-registry-change-plan.schema.json",
        "schema_version": 1,
        "skill_id": candidate.skill_id,
        "candidate_id": candidate.candidate_id,
        "candidate_digest": candidate.candidate_digest,
        "evaluation_digest": evaluation.evaluation_digest,
        "proposed_by_ref": candidate.proposed_by_ref,
        "proposer_identity_digest": candidate.proposer_identity_digest,
        "evaluator_identity_digest": evaluation.evaluator_identity_digest,
        "verifier_identity_digest": evaluation.verifier_identity_digest,
        "approver_identity_digest": approver_identity_digest,
        "state": "approval-required",
        "from_state": "evaluated",
        "to_state": "active",
        "expected_registry_digest": previous,
        "registry_record_digest": registry_digest,
        "rollback_target_ref": rollback,
        "supersedes_ref": supersedes,
        "mutation": mutation.as_dict(),
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["plan_digest"] = _digest(_registry_plan_identity(payload))
    return parse_skill_registry_change_plan(payload)


def _parse_mutation(payload: object) -> MutationPlan:
    data = _strict(
        payload,
        {"schema_version", "plan_id", "operation", "target_ref", "ownership", "change_digest", "dry_run_required", "approval_required", "reversible"},
        "skill mutation",
    )
    if data.get("schema_version") != 1:
        raise SkillLifecycleError("skill mutation schema_version must be 1")
    plan = MutationPlan(
        _sha256(data.get("plan_id"), "mutation plan_id"),
        str(data.get("operation")),
        str(data.get("target_ref")),
        str(data.get("ownership")),
        _sha256(data.get("change_digest"), "mutation change_digest"),
        data.get("dry_run_required") is True,
        data.get("approval_required") is True,
        data.get("reversible") is True,
    )
    if (
        plan.operation not in {"create", "update"}
        or plan.ownership != "user-data"
        or not plan.dry_run_required
        or not plan.approval_required
        or not plan.reversible
    ):
        raise SkillLifecycleError("skill mutation contract is unsafe")
    identity = {
        "operation": plan.operation,
        "target_ref": plan.target_ref,
        "ownership": plan.ownership,
        "change_digest": plan.change_digest,
        "reversible": plan.reversible,
    }
    expected_plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if plan.plan_id != expected_plan_id:
        raise SkillLifecycleError("skill mutation plan_id does not match")
    return plan


def parse_skill_registry_change_plan(payload: object) -> SkillRegistryChangePlan:
    expected = {
        "schema_ref", "schema_version", "skill_id", "candidate_id",
        "candidate_digest", "evaluation_digest", "proposed_by_ref",
        "proposer_identity_digest", "evaluator_identity_digest",
        "verifier_identity_digest", "approver_identity_digest", "state",
        "from_state", "to_state", "expected_registry_digest",
        "registry_record_digest", "rollback_target_ref", "supersedes_ref",
        "mutation", "plan_digest", "invariants",
    }
    data = _strict(payload, expected, "skill registry change plan")
    if (
        data.get("schema_ref") != "schemas/skill-registry-change-plan.schema.json"
        or data.get("schema_version") != 1
        or data.get("state") != "approval-required"
        or data.get("invariants") != PUBLIC_INVARIANTS
    ):
        raise SkillLifecycleError("skill registry change plan contract is invalid")
    skill_id = _identifier(data.get("skill_id"), "skill_id")
    candidate_id = _identifier(data.get("candidate_id"), "candidate_id")
    candidate_digest = _sha256(data.get("candidate_digest"), "candidate_digest")
    evaluation_digest = _sha256(data.get("evaluation_digest"), "evaluation_digest")
    proposed_by_ref = _logical_ref(data.get("proposed_by_ref"), "proposed_by_ref")
    identity_digests = tuple(
        _sha256(data.get(name), name)
        for name in (
            "proposer_identity_digest", "evaluator_identity_digest",
            "verifier_identity_digest", "approver_identity_digest",
        )
    )
    if len(set(identity_digests)) != 4:
        raise SkillLifecycleError("proposer, evaluator, verifier, and approver identities must be distinct")
    from_state, to_state = data.get("from_state"), data.get("to_state")
    if from_state not in STATES or to_state not in STATES or (from_state, to_state) not in {
        ("evaluated", "active"), ("active", "deprecated"),
        ("active", "retired"), ("deprecated", "retired"),
    }:
        raise SkillLifecycleError("skill lifecycle transition is invalid")
    previous = data.get("expected_registry_digest")
    if previous is not None:
        previous = _sha256(previous, "expected_registry_digest")
    registry_digest = _sha256(data.get("registry_record_digest"), "registry_record_digest")
    rollback = _logical_ref(data.get("rollback_target_ref"), "rollback_target_ref")
    supersedes = data.get("supersedes_ref")
    if supersedes is not None:
        supersedes = _logical_ref(supersedes, "supersedes_ref")
    mutation = _parse_mutation(data.get("mutation"))
    expected_target = f".krcn/global/knowledge/skill-registry/{skill_id}.json"
    if mutation.change_digest != registry_digest or mutation.target_ref != expected_target:
        raise SkillLifecycleError("skill mutation does not bind the registry record")
    if (previous is None) != (mutation.operation == "create"):
        raise SkillLifecycleError("skill mutation operation does not match registry state")
    plan_digest = _sha256(data.get("plan_digest"), "plan_digest")
    if plan_digest != _digest(_registry_plan_identity(data)):
        raise SkillLifecycleError("skill registry plan digest does not match")
    return SkillRegistryChangePlan(
        skill_id, candidate_id, candidate_digest, evaluation_digest,
        proposed_by_ref, identity_digests[0], identity_digests[1],
        identity_digests[2], identity_digests[3], str(from_state), str(to_state), previous,
        registry_digest, rollback, supersedes, mutation, plan_digest,
    )


@dataclass(frozen=True)
class SkillLifecycleRecord:
    skill_id: str
    candidate_id: str
    candidate_digest: str
    evaluation_digest: str
    proposed_by_ref: str
    proposer_identity_digest: str
    evaluator_identity_digest: str
    verifier_identity_digest: str
    approver_identity_digest: str
    state: str
    previous_state: str
    registry_record_digest: str
    registry_plan_id: str
    changed_by_ref: str
    rollback_target_ref: str
    supersedes_ref: str | None
    lifecycle_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/skill-lifecycle-record.schema.json",
            "schema_version": 1,
            "skill_id": self.skill_id,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "evaluation_digest": self.evaluation_digest,
            "proposed_by_ref": self.proposed_by_ref,
            "proposer_identity_digest": self.proposer_identity_digest,
            "evaluator_identity_digest": self.evaluator_identity_digest,
            "verifier_identity_digest": self.verifier_identity_digest,
            "approver_identity_digest": self.approver_identity_digest,
            "state": self.state,
            "previous_state": self.previous_state,
            "registry_record_digest": self.registry_record_digest,
            "registry_plan_id": self.registry_plan_id,
            "changed_by_ref": self.changed_by_ref,
            "rollback_target_ref": self.rollback_target_ref,
            "supersedes_ref": self.supersedes_ref,
            "lifecycle_digest": self.lifecycle_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def _lifecycle_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in payload if key not in {"schema_ref", "schema_version", "lifecycle_digest"}}


def finalize_skill_registry_change(
    plan: SkillRegistryChangePlan,
    authorization: MutationAuthorization,
    *,
    changed_by_ref: str,
    changed_by_identity_digest: str,
) -> SkillLifecycleRecord:
    """Finalize lifecycle metadata only; the registry owner performs the write."""

    plan = parse_skill_registry_change_plan(plan.as_payload())
    actor = _logical_ref(changed_by_ref, "changed_by_ref")
    actor_identity_digest = _sha256(changed_by_identity_digest, "changed_by_identity_digest")
    if actor_identity_digest != plan.approver_identity_digest:
        raise SkillLifecycleError("finalizing actor does not match the approved stable identity")
    if (
        authorization.plan != plan.mutation
        or not authorization.dry_run_verified
        or not authorization.approval_verified
    ):
        raise SkillLifecycleError("exact approved registry mutation authorization is required")
    payload: dict[str, object] = {
        "schema_ref": "schemas/skill-lifecycle-record.schema.json",
        "schema_version": 1,
        "skill_id": plan.skill_id,
        "candidate_id": plan.candidate_id,
        "candidate_digest": plan.candidate_digest,
        "evaluation_digest": plan.evaluation_digest,
        "proposed_by_ref": plan.proposed_by_ref,
        "proposer_identity_digest": plan.proposer_identity_digest,
        "evaluator_identity_digest": plan.evaluator_identity_digest,
        "verifier_identity_digest": plan.verifier_identity_digest,
        "approver_identity_digest": plan.approver_identity_digest,
        "state": plan.to_state,
        "previous_state": plan.from_state,
        "registry_record_digest": plan.registry_record_digest,
        "registry_plan_id": plan.mutation.plan_id,
        "changed_by_ref": actor,
        "rollback_target_ref": plan.rollback_target_ref,
        "supersedes_ref": plan.supersedes_ref,
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["lifecycle_digest"] = _digest(_lifecycle_identity(payload))
    return parse_skill_lifecycle_record(payload)


def parse_skill_lifecycle_record(payload: object) -> SkillLifecycleRecord:
    expected = {
        "schema_ref", "schema_version", "skill_id", "candidate_id",
        "candidate_digest", "evaluation_digest", "proposed_by_ref",
        "proposer_identity_digest", "evaluator_identity_digest",
        "verifier_identity_digest", "approver_identity_digest", "state", "previous_state",
        "registry_record_digest", "registry_plan_id", "changed_by_ref",
        "rollback_target_ref", "supersedes_ref", "lifecycle_digest", "invariants",
    }
    data = _strict(payload, expected, "skill lifecycle record")
    if (
        data.get("schema_ref") != "schemas/skill-lifecycle-record.schema.json"
        or data.get("schema_version") != 1
        or data.get("invariants") != PUBLIC_INVARIANTS
    ):
        raise SkillLifecycleError("skill lifecycle record contract is invalid")
    state, previous = data.get("state"), data.get("previous_state")
    if (previous, state) not in {
        ("evaluated", "active"), ("active", "deprecated"),
        ("active", "retired"), ("deprecated", "retired"),
    }:
        raise SkillLifecycleError("skill lifecycle record transition is invalid")
    values = (
        _identifier(data.get("skill_id"), "skill_id"),
        _identifier(data.get("candidate_id"), "candidate_id"),
        _sha256(data.get("candidate_digest"), "candidate_digest"),
        _sha256(data.get("evaluation_digest"), "evaluation_digest"),
        _logical_ref(data.get("proposed_by_ref"), "proposed_by_ref"),
        _sha256(data.get("registry_record_digest"), "registry_record_digest"),
        _sha256(data.get("registry_plan_id"), "registry_plan_id"),
        _logical_ref(data.get("changed_by_ref"), "changed_by_ref"),
        _logical_ref(data.get("rollback_target_ref"), "rollback_target_ref"),
    )
    identity_digests = tuple(
        _sha256(data.get(name), name)
        for name in (
            "proposer_identity_digest", "evaluator_identity_digest",
            "verifier_identity_digest", "approver_identity_digest",
        )
    )
    if len(set(identity_digests)) != 4:
        raise SkillLifecycleError("lifecycle actor identities must be distinct")
    supersedes = data.get("supersedes_ref")
    if supersedes is not None:
        supersedes = _logical_ref(supersedes, "supersedes_ref")
    lifecycle_digest = _sha256(data.get("lifecycle_digest"), "lifecycle_digest")
    if lifecycle_digest != _digest(_lifecycle_identity(data)):
        raise SkillLifecycleError("skill lifecycle digest does not match")
    return SkillLifecycleRecord(
        values[0], values[1], values[2], values[3], values[4],
        identity_digests[0], identity_digests[1], identity_digests[2],
        identity_digests[3], str(state), str(previous), values[5], values[6],
        values[7], values[8], supersedes, lifecycle_digest,
    )


def prepare_skill_state_change(
    resolver: OwnershipResolver,
    current: SkillLifecycleRecord,
    *,
    to_state: str,
    rollback_target_ref: str,
    approver_identity_digest: str,
    supersedes_ref: str | None = None,
) -> SkillRegistryChangePlan:
    current = parse_skill_lifecycle_record(current.as_payload())
    if (current.state, to_state) not in {
        ("active", "deprecated"), ("active", "retired"), ("deprecated", "retired"),
    }:
        raise SkillLifecycleError("skill lifecycle transition is invalid")
    rollback = _logical_ref(rollback_target_ref, "rollback_target_ref")
    supersedes = None if supersedes_ref is None else _logical_ref(supersedes_ref, "supersedes_ref")
    approver_identity_digest = _sha256(approver_identity_digest, "approver_identity_digest")
    if approver_identity_digest in {
        current.proposer_identity_digest,
        current.evaluator_identity_digest,
        current.verifier_identity_digest,
    }:
        raise SkillLifecycleError("proposer, evaluator, verifier, and approver identities must be distinct")
    registry_digest = _digest(
        {
            "skill_id": current.skill_id,
            "candidate_digest": current.candidate_digest,
            "evaluation_digest": current.evaluation_digest,
            "state": to_state,
            "rollback_target_ref": rollback,
            "supersedes_ref": supersedes,
            "expected_registry_digest": current.registry_record_digest,
            "invariants": PUBLIC_INVARIANTS,
        }
    )
    mutation = plan_mutation(
        resolver,
        operation="update",
        target_ref=f".krcn/global/knowledge/skill-registry/{current.skill_id}.json",
        expected_ownership="user-data",
        change_digest=registry_digest,
        reversible=True,
    )
    payload: dict[str, object] = {
        "schema_ref": "schemas/skill-registry-change-plan.schema.json",
        "schema_version": 1,
        "skill_id": current.skill_id,
        "candidate_id": current.candidate_id,
        "candidate_digest": current.candidate_digest,
        "evaluation_digest": current.evaluation_digest,
        "proposed_by_ref": current.proposed_by_ref,
        "proposer_identity_digest": current.proposer_identity_digest,
        "evaluator_identity_digest": current.evaluator_identity_digest,
        "verifier_identity_digest": current.verifier_identity_digest,
        "approver_identity_digest": approver_identity_digest,
        "state": "approval-required",
        "from_state": current.state,
        "to_state": to_state,
        "expected_registry_digest": current.registry_record_digest,
        "registry_record_digest": registry_digest,
        "rollback_target_ref": rollback,
        "supersedes_ref": supersedes,
        "mutation": mutation.as_dict(),
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["plan_digest"] = _digest(_registry_plan_identity(payload))
    return parse_skill_registry_change_plan(payload)

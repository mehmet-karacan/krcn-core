"""Approval-gated durable memory lifecycle and separate policy promotion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .information_records import (
    EvidenceRef,
    InformationRecord,
    InformationRecordError,
    Provenance,
    canonical_json,
    parse_information_record,
    validate_memory_record,
)
from .local_store import LocalWorkspaceStore, RecordWritePlan, StoredRecord
from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .policies import UserPolicy, UserPolicyError, parse_user_policy


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
MEMORY_ORIGINS = {
    "explicit-user",
    "conversation-summary",
    "inference",
    "source-derived",
}
REVIEW_OUTCOMES = {"approved", "rejected", "needs-changes"}
ACTION_TYPES = {"supersede", "revoke"}
RESTRICTION_RANK = {"allow": 1, "require-approval": 2, "deny": 3}


class MemoryGateError(ValueError):
    """Raised when durable memory would bypass review, approval, or policy."""


@dataclass(frozen=True)
class MemoryCandidate:
    candidate_id: str
    origin: str
    proposed_memory: InformationRecord
    conflict_refs: tuple[str, ...]
    policy_promotion: bool
    candidate_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/memory-candidate.schema.json",
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "origin": self.origin,
            "proposed_memory": self.proposed_memory.as_payload(),
            "conflict_refs": list(self.conflict_refs),
            "policy_promotion": self.policy_promotion,
            "candidate_digest": self.candidate_digest,
        }


@dataclass(frozen=True)
class MemoryReview:
    review_id: str
    candidate_id: str
    candidate_digest: str
    outcome: str
    reviewed_by: str
    session_id: str
    approval_id: str | None
    acknowledged_conflict_refs: tuple[str, ...]
    review_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/memory-review.schema.json",
            "schema_version": 1,
            "review_id": self.review_id,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "outcome": self.outcome,
            "reviewed_by": self.reviewed_by,
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "acknowledged_conflict_refs": list(
                self.acknowledged_conflict_refs
            ),
            "review_digest": self.review_digest,
        }


@dataclass(frozen=True)
class MemoryPersistencePlan:
    candidate_digest: str
    review_digest: str
    memory_record: InformationRecord
    write_plan: RecordWritePlan

    def public_summary(self) -> dict[str, object]:
        return {
            "candidate_digest": self.candidate_digest,
            "review_digest": self.review_digest,
            "memory": self.memory_record.public_summary(),
            "write": self.write_plan.public_summary(),
        }


@dataclass(frozen=True)
class MemoryAction:
    action_id: str
    action: str
    memory_id: str
    expected_revision: int
    expected_content_digest: str
    replacement_ref: str | None
    session_id: str
    approval_id: str
    approved: bool
    action_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/memory-action.schema.json",
            "schema_version": 1,
            "action_id": self.action_id,
            "action": self.action,
            "memory_id": self.memory_id,
            "expected_revision": self.expected_revision,
            "expected_content_digest": self.expected_content_digest,
            "replacement_ref": self.replacement_ref,
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "approved": self.approved,
            "action_digest": self.action_digest,
        }


@dataclass(frozen=True)
class MemoryLifecyclePlan:
    action_digest: str
    memory_record: InformationRecord
    write_plan: RecordWritePlan


@dataclass(frozen=True)
class PolicyPromotionPlan:
    memory_id: str
    memory_revision: int
    memory_digest: str
    policy_id: str
    policy_revision: int
    policy_payload_digest: str
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/policy-promotion-plan.schema.json",
            "schema_version": 1,
            "memory_id": self.memory_id,
            "memory_revision": self.memory_revision,
            "memory_digest": self.memory_digest,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "policy_payload_digest": self.policy_payload_digest,
            "separate_policy_mutation": self.mutation.as_dict(),
        }


def _logical_ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise MemoryGateError(f"{label} must be a logical reference")
    if ".." in value.split(":", 1)[1].split("/") or "://" in value:
        raise MemoryGateError(f"{label} must be portable")
    return value


def _memory_payload(record: InformationRecord) -> None:
    try:
        validate_memory_record(record)
    except InformationRecordError as exc:
        raise MemoryGateError(str(exc)) from exc


def memory_candidate_digest(
    candidate_id: str,
    origin: str,
    proposed_memory: InformationRecord,
    conflict_refs: tuple[str, ...],
    policy_promotion: bool,
) -> str:
    identity = {
        "candidate_id": candidate_id,
        "origin": origin,
        "proposed_memory": proposed_memory.as_payload(),
        "conflict_refs": list(conflict_refs),
        "policy_promotion": policy_promotion,
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def parse_memory_candidate(payload: object) -> MemoryCandidate:
    expected = {
        "schema_ref",
        "schema_version",
        "candidate_id",
        "origin",
        "proposed_memory",
        "conflict_refs",
        "policy_promotion",
        "candidate_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise MemoryGateError("memory candidate fields are invalid")
    if payload.get("schema_ref") != "schemas/memory-candidate.schema.json":
        raise MemoryGateError("memory candidate schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise MemoryGateError("memory candidate schema_version must be 1")
    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not IDENTIFIER.fullmatch(candidate_id):
        raise MemoryGateError("memory candidate_id is invalid")
    origin = payload.get("origin")
    if not isinstance(origin, str) or origin not in MEMORY_ORIGINS:
        raise MemoryGateError("memory candidate origin is invalid")
    try:
        proposed = parse_information_record(payload.get("proposed_memory"))
    except InformationRecordError as exc:
        raise MemoryGateError("proposed memory record is invalid") from exc
    _memory_payload(proposed)
    if proposed.lifecycle != "current":
        raise MemoryGateError("proposed memory must be current")
    conflicts_payload = payload.get("conflict_refs")
    if not isinstance(conflicts_payload, list):
        raise MemoryGateError("memory conflict_refs must be a list")
    conflicts = tuple(
        _logical_ref(item, "memory conflict_ref") for item in conflicts_payload
    )
    if len(set(conflicts)) != len(conflicts):
        raise MemoryGateError("memory conflict_refs must be unique")
    conflicts = tuple(sorted(conflicts))
    policy_promotion = payload.get("policy_promotion")
    if policy_promotion is not False:
        raise MemoryGateError("memory candidate cannot promote itself to policy")
    digest = payload.get("candidate_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise MemoryGateError("memory candidate digest is invalid")
    if digest != memory_candidate_digest(
        candidate_id,
        origin,
        proposed,
        conflicts,
        False,
    ):
        raise MemoryGateError("memory candidate digest does not match")
    return MemoryCandidate(
        candidate_id=candidate_id,
        origin=origin,
        proposed_memory=proposed,
        conflict_refs=conflicts,
        policy_promotion=False,
        candidate_digest=digest,
    )


def memory_review_digest(
    review_id: str,
    candidate_id: str,
    candidate_digest: str,
    outcome: str,
    reviewed_by: str,
    session_id: str,
    approval_id: str | None,
    acknowledged_conflict_refs: tuple[str, ...],
) -> str:
    identity = {
        "review_id": review_id,
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "outcome": outcome,
        "reviewed_by": reviewed_by,
        "session_id": session_id,
        "approval_id": approval_id,
        "acknowledged_conflict_refs": list(acknowledged_conflict_refs),
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def parse_memory_review(payload: object) -> MemoryReview:
    expected = {
        "schema_ref",
        "schema_version",
        "review_id",
        "candidate_id",
        "candidate_digest",
        "outcome",
        "reviewed_by",
        "session_id",
        "approval_id",
        "acknowledged_conflict_refs",
        "review_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise MemoryGateError("memory review fields are invalid")
    if payload.get("schema_ref") != "schemas/memory-review.schema.json":
        raise MemoryGateError("memory review schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise MemoryGateError("memory review schema_version must be 1")
    review_id = payload.get("review_id")
    candidate_id = payload.get("candidate_id")
    for value, label in (
        (review_id, "review_id"),
        (candidate_id, "candidate_id"),
    ):
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            raise MemoryGateError(f"memory {label} is invalid")
    candidate_digest = payload.get("candidate_digest")
    if not isinstance(candidate_digest, str) or not SHA256.fullmatch(candidate_digest):
        raise MemoryGateError("memory review candidate_digest is invalid")
    outcome = payload.get("outcome")
    if not isinstance(outcome, str) or outcome not in REVIEW_OUTCOMES:
        raise MemoryGateError("memory review outcome is invalid")
    reviewed_by = payload.get("reviewed_by")
    if (
        not isinstance(reviewed_by, str)
        or reviewed_by not in {"user", "delegate"}
    ):
        raise MemoryGateError("memory reviewed_by is invalid")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise MemoryGateError("memory review session_id is invalid")
    approval_id = payload.get("approval_id")
    if outcome == "approved":
        if reviewed_by != "user":
            raise MemoryGateError("durable memory approval must come from the user")
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise MemoryGateError("approved memory requires approval_id")
    elif approval_id is not None:
        raise MemoryGateError("non-approved review must not contain approval_id")
    conflicts_payload = payload.get("acknowledged_conflict_refs")
    if not isinstance(conflicts_payload, list):
        raise MemoryGateError("acknowledged conflicts must be a list")
    conflicts = tuple(
        _logical_ref(item, "acknowledged conflict_ref")
        for item in conflicts_payload
    )
    if len(set(conflicts)) != len(conflicts):
        raise MemoryGateError("acknowledged conflicts must be unique")
    conflicts = tuple(sorted(conflicts))
    digest = payload.get("review_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise MemoryGateError("memory review digest is invalid")
    if digest != memory_review_digest(
        str(review_id),
        str(candidate_id),
        candidate_digest,
        outcome,
        str(reviewed_by),
        session_id,
        approval_id,
        conflicts,
    ):
        raise MemoryGateError("memory review digest does not match")
    return MemoryReview(
        review_id=str(review_id),
        candidate_id=str(candidate_id),
        candidate_digest=candidate_digest,
        outcome=outcome,
        reviewed_by=str(reviewed_by),
        session_id=session_id,
        approval_id=approval_id,
        acknowledged_conflict_refs=conflicts,
        review_digest=digest,
    )


def _approved_memory_record(
    candidate: MemoryCandidate,
    review: MemoryReview,
) -> InformationRecord:
    evidence = list(candidate.proposed_memory.provenance.evidence)
    evidence.append(
        EvidenceRef(
            f"review:{review.review_id}",
            "1",
            review.review_digest,
            "supersedes",
        )
    )
    provenance = Provenance(
        "approved-memory",
        tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.source_ref,
                    item.revision_id,
                    item.digest,
                    item.relation,
                ),
            )
        ),
    )
    payload = candidate.proposed_memory.as_payload()
    payload["provenance"] = provenance.as_dict()
    return parse_information_record(payload)


def prepare_memory_persistence(
    store: LocalWorkspaceStore,
    candidate: MemoryCandidate,
    review: MemoryReview,
    *,
    expected_revision: int,
) -> MemoryPersistencePlan:
    candidate = parse_memory_candidate(candidate.as_payload())
    review = parse_memory_review(review.as_payload())
    if (
        review.candidate_id != candidate.candidate_id
        or review.candidate_digest != candidate.candidate_digest
    ):
        raise MemoryGateError("memory review does not match the candidate")
    if review.outcome != "approved":
        raise MemoryGateError("memory candidate is not approved for persistence")
    if review.acknowledged_conflict_refs != candidate.conflict_refs:
        raise MemoryGateError("memory conflicts were not reviewed exactly")
    if any(item.startswith("policy:") for item in candidate.conflict_refs):
        raise MemoryGateError("memory cannot override an active user policy")
    memory_record = _approved_memory_record(candidate, review)
    try:
        write_plan = store.prepare_put(
            "memory",
            memory_record.record_id,
            memory_record.as_payload(),
            expected_revision=expected_revision,
        )
    except ValueError as exc:
        raise MemoryGateError(str(exc)) from exc
    return MemoryPersistencePlan(
        candidate_digest=candidate.candidate_digest,
        review_digest=review.review_digest,
        memory_record=memory_record,
        write_plan=write_plan,
    )


def apply_memory_persistence(
    store: LocalWorkspaceStore,
    plan: MemoryPersistencePlan,
    candidate: MemoryCandidate,
    review: MemoryReview,
    authorization: MutationAuthorization,
) -> StoredRecord:
    candidate = parse_memory_candidate(candidate.as_payload())
    review = parse_memory_review(review.as_payload())
    if (
        candidate.candidate_digest != plan.candidate_digest
        or review.review_digest != plan.review_digest
    ):
        raise MemoryGateError("memory persistence evidence changed after planning")
    try:
        return store.apply_put(plan.write_plan, authorization)
    except ValueError as exc:
        raise MemoryGateError(str(exc)) from exc


def memory_action_digest(
    action_id: str,
    action: str,
    memory_id: str,
    expected_revision: int,
    expected_content_digest: str,
    replacement_ref: str | None,
    session_id: str,
    approval_id: str,
    approved: bool,
) -> str:
    identity = {
        "action_id": action_id,
        "action": action,
        "memory_id": memory_id,
        "expected_revision": expected_revision,
        "expected_content_digest": expected_content_digest,
        "replacement_ref": replacement_ref,
        "session_id": session_id,
        "approval_id": approval_id,
        "approved": approved,
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def parse_memory_action(payload: object) -> MemoryAction:
    expected = {
        "schema_ref",
        "schema_version",
        "action_id",
        "action",
        "memory_id",
        "expected_revision",
        "expected_content_digest",
        "replacement_ref",
        "session_id",
        "approval_id",
        "approved",
        "action_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise MemoryGateError("memory action fields are invalid")
    if payload.get("schema_ref") != "schemas/memory-action.schema.json":
        raise MemoryGateError("memory action schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise MemoryGateError("memory action schema_version must be 1")
    action_id = payload.get("action_id")
    memory_id = payload.get("memory_id")
    for value, label in ((action_id, "action_id"), (memory_id, "memory_id")):
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            raise MemoryGateError(f"memory {label} is invalid")
    action = payload.get("action")
    if not isinstance(action, str) or action not in ACTION_TYPES:
        raise MemoryGateError("memory action type is invalid")
    expected_revision = payload.get("expected_revision")
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise MemoryGateError("memory action revision is invalid")
    expected_content_digest = payload.get("expected_content_digest")
    if (
        not isinstance(expected_content_digest, str)
        or not SHA256.fullmatch(expected_content_digest)
    ):
        raise MemoryGateError("memory action content digest is invalid")
    replacement_payload = payload.get("replacement_ref")
    replacement_ref = (
        None
        if replacement_payload is None
        else _logical_ref(replacement_payload, "memory replacement_ref")
    )
    if replacement_ref is not None and not replacement_ref.startswith("memory:"):
        raise MemoryGateError("replacement_ref must identify memory")
    if action == "supersede" and replacement_ref is None:
        raise MemoryGateError("supersede requires replacement_ref")
    if action == "revoke" and replacement_ref is not None:
        raise MemoryGateError("revoke must not contain replacement_ref")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise MemoryGateError("memory action session_id is invalid")
    approval_id = payload.get("approval_id")
    approved = payload.get("approved")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise MemoryGateError("memory action approval_id is required")
    if approved is not True:
        raise MemoryGateError("memory action requires explicit approval")
    digest = payload.get("action_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise MemoryGateError("memory action digest is invalid")
    if digest != memory_action_digest(
        str(action_id),
        action,
        str(memory_id),
        expected_revision,
        expected_content_digest,
        replacement_ref,
        session_id,
        approval_id,
        True,
    ):
        raise MemoryGateError("memory action digest does not match")
    return MemoryAction(
        action_id=str(action_id),
        action=action,
        memory_id=str(memory_id),
        expected_revision=expected_revision,
        expected_content_digest=expected_content_digest,
        replacement_ref=replacement_ref,
        session_id=session_id,
        approval_id=approval_id,
        approved=True,
        action_digest=digest,
    )


def _stored_memory(stored: StoredRecord) -> InformationRecord:
    try:
        record = parse_information_record(dict(stored.payload))
    except InformationRecordError as exc:
        raise MemoryGateError("stored memory record is invalid") from exc
    _memory_payload(record)
    if record.revision != stored.revision:
        raise MemoryGateError("stored memory revision does not match")
    return record


def prepare_memory_lifecycle(
    store: LocalWorkspaceStore,
    action: MemoryAction,
) -> MemoryLifecyclePlan:
    action = parse_memory_action(action.as_payload())
    stored = store.read("memory", action.memory_id)
    if stored is None:
        raise MemoryGateError("memory record was not found")
    current = _stored_memory(stored)
    if current.lifecycle != "current":
        raise MemoryGateError("only current memory can change lifecycle")
    if (
        current.revision != action.expected_revision
        or current.content_digest != action.expected_content_digest
    ):
        raise MemoryGateError("memory action targets a stale revision")
    evidence = list(current.provenance.evidence)
    evidence.append(
        EvidenceRef(
            action.replacement_ref or f"action:{action.action_id}",
            "pending" if action.replacement_ref else "1",
            action.action_digest,
            "supersedes" if action.action == "supersede" else "observed-at",
        )
    )
    payload = current.as_payload()
    payload["revision"] = current.revision + 1
    payload["lifecycle"] = (
        "superseded" if action.action == "supersede" else "archived"
    )
    payload["provenance"] = Provenance(
        "approved-memory",
        tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.source_ref,
                    item.revision_id,
                    item.digest,
                    item.relation,
                ),
            )
        ),
    ).as_dict()
    updated = parse_information_record(payload)
    try:
        write_plan = store.prepare_put(
            "memory",
            current.record_id,
            updated.as_payload(),
            expected_revision=current.revision,
        )
    except ValueError as exc:
        raise MemoryGateError(str(exc)) from exc
    return MemoryLifecyclePlan(action.action_digest, updated, write_plan)


def apply_memory_lifecycle(
    store: LocalWorkspaceStore,
    plan: MemoryLifecyclePlan,
    action: MemoryAction,
    authorization: MutationAuthorization,
) -> StoredRecord:
    action = parse_memory_action(action.as_payload())
    if action.action_digest != plan.action_digest:
        raise MemoryGateError("memory action changed after planning")
    try:
        return store.apply_put(plan.write_plan, authorization)
    except ValueError as exc:
        raise MemoryGateError(str(exc)) from exc


def _restriction_map(policy: UserPolicy) -> dict[tuple[object, ...], int]:
    restrictions: dict[tuple[object, ...], int] = {}
    for rule in policy.rules:
        if not rule.active or rule.effect == "allow":
            continue
        for operation in rule.operations:
            key = (
                policy.scope.kind,
                policy.scope.ref,
                rule.resource_type,
                operation,
            )
            restrictions[key] = max(
                restrictions.get(key, 0),
                RESTRICTION_RANK[rule.effect],
            )
    return restrictions


def _all_effects(policy: UserPolicy) -> dict[tuple[object, ...], int]:
    effects: dict[tuple[object, ...], int] = {}
    for rule in policy.rules:
        if not rule.active:
            continue
        for operation in rule.operations:
            key = (
                policy.scope.kind,
                policy.scope.ref,
                rule.resource_type,
                operation,
            )
            effects[key] = max(effects.get(key, 0), RESTRICTION_RANK[rule.effect])
    return effects


def prepare_policy_promotion(
    memory: InformationRecord,
    proposed_policy_payload: Mapping[str, object],
    ownership: OwnershipResolver,
    *,
    existing_policy: UserPolicy | None = None,
) -> PolicyPromotionPlan:
    try:
        memory = parse_information_record(memory.as_payload())
    except InformationRecordError as exc:
        raise MemoryGateError("policy promotion memory is invalid") from exc
    _memory_payload(memory)
    if memory.provenance.kind != "approved-memory" or memory.lifecycle != "current":
        raise MemoryGateError("only current approved memory may propose policy")
    try:
        proposed_policy = parse_user_policy(dict(proposed_policy_payload))
    except UserPolicyError as exc:
        raise MemoryGateError("proposed policy is invalid") from exc
    expected_evidence = f"memory:{memory.record_id}"
    for rule in proposed_policy.rules:
        if (
            rule.active
            and (
                rule.provenance != "approved-memory"
                or rule.evidence_ref != expected_evidence
            )
        ):
            raise MemoryGateError(
                "policy promotion must cite the approved memory exactly"
            )
    if existing_policy is not None:
        if existing_policy.policy_id != proposed_policy.policy_id:
            raise MemoryGateError("existing policy identity does not match")
        old_restrictions = _restriction_map(existing_policy)
        new_effects = _all_effects(proposed_policy)
        if any(
            new_effects.get(key, 0) < required_rank
            for key, required_rank in old_restrictions.items()
        ):
            raise MemoryGateError("policy promotion would weaken an active restriction")
    policy_digest = hashlib.sha256(
        canonical_json(dict(proposed_policy_payload))
    ).hexdigest()
    mutation = plan_mutation(
        ownership,
        operation="update" if existing_policy is not None else "create",
        target_ref=f".krcn/policies/{proposed_policy.policy_id}.json",
        expected_ownership="user-data",
        change_digest=policy_digest,
        reversible=True,
    )
    return PolicyPromotionPlan(
        memory_id=memory.record_id,
        memory_revision=memory.revision,
        memory_digest=memory.content_digest,
        policy_id=proposed_policy.policy_id,
        policy_revision=proposed_policy.revision,
        policy_payload_digest=policy_digest,
        mutation=mutation,
    )

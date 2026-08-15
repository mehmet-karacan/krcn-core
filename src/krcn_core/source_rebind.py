"""Exact-plan relocation of an external source binding without source writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .discovery import DiscoveryResult
from .local_store import LocalWorkspaceStore, RecordWritePlan, StoredRecord
from .mutation_gate import MutationAuthorization
from .source_bindings import SourceBinding, SourceLocator
from .source_identity import (
    SourceIdentity,
    assert_external_source,
    identities_match,
    source_identity_from_discovery,
    source_identity_from_state,
)
from .source_state import parse_source_state, source_state_from_discovery


class SourceRebindError(ValueError):
    """Raised when an external source cannot be rebound safely."""


REVISION_RELATIONS = {
    "linear-history",
    "diverged-history",
    "unrelated-history",
}


@dataclass(frozen=True)
class SourceRelocationAssessment:
    """Path-redacted classification of one source relocation candidate."""

    classification: str
    source_id: str
    binding_id: str
    expected_digest: str
    candidate_digest: str
    rebind_allowed: bool
    integration_required: bool
    reconciliation_required: bool
    index_action: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/source-relocation-assessment.schema.json",
            "schema_version": 1,
            "classification": self.classification,
            "source_id": self.source_id,
            "binding_id": self.binding_id,
            "expected_digest": self.expected_digest,
            "candidate_digest": self.candidate_digest,
            "rebind_allowed": self.rebind_allowed,
            "integration_required": self.integration_required,
            "reconciliation_required": self.reconciliation_required,
            "index_action": self.index_action,
            "candidate_path_disclosed": False,
            "source_effect": "read-only",
            "grants_authority": False,
        }


def classify_source_relocation(
    expected: SourceIdentity,
    candidate: SourceIdentity,
    *,
    revision_relation: str | None = None,
) -> SourceRelocationAssessment:
    """Classify relocation without treating a changed digest as a path move.

    `revision_relation` is reviewed Git relationship evidence supplied by a
    read-only adapter. A changed digest without that evidence remains
    indeterminate and is rejected instead of guessed from a folder or repo name.
    """

    logical_match = (
        expected.source_id == candidate.source_id
        and expected.binding_id == candidate.binding_id
        and expected.algorithm == candidate.algorithm
    )
    if not logical_match:
        return SourceRelocationAssessment(
            "unrelated-source",
            candidate.source_id,
            candidate.binding_id,
            expected.digest,
            candidate.digest,
            False,
            False,
            False,
            "create-separate-project",
        )
    if expected.digest == candidate.digest and expected.file_count == candidate.file_count:
        return SourceRelocationAssessment(
            "relocated-same-source",
            candidate.source_id,
            candidate.binding_id,
            expected.digest,
            candidate.digest,
            True,
            False,
            False,
            "verify-current-manifest-and-reuse",
        )
    if revision_relation not in REVISION_RELATIONS:
        raise SourceRebindError(
            "candidate content changed; reviewed Git relationship evidence is required"
        )
    if revision_relation == "linear-history":
        return SourceRelocationAssessment(
            "same-project-new-revision",
            candidate.source_id,
            candidate.binding_id,
            expected.digest,
            candidate.digest,
            False,
            True,
            False,
            "mark-stale-and-rebuild",
        )
    if revision_relation == "diverged-history":
        return SourceRelocationAssessment(
            "diverged-clone",
            candidate.source_id,
            candidate.binding_id,
            expected.digest,
            candidate.digest,
            False,
            False,
            True,
            "separate-revision-index",
        )
    return SourceRelocationAssessment(
        "unrelated-source",
        candidate.source_id,
        candidate.binding_id,
        expected.digest,
        candidate.digest,
        False,
        False,
        False,
        "create-separate-project",
    )


@dataclass(frozen=True)
class SourceRebindPlan:
    plan_id: str
    binding_id: str
    source_id: str
    previous_binding_revision: int
    next_binding_revision: int
    candidate_root: Path
    expected_identity: SourceIdentity
    candidate_identity: SourceIdentity
    assessment: SourceRelocationAssessment
    record_plans: tuple[RecordWritePlan, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "binding_id": self.binding_id,
            "source_id": self.source_id,
            "previous_binding_revision": self.previous_binding_revision,
            "next_binding_revision": self.next_binding_revision,
            "identity_verified": identities_match(
                self.expected_identity,
                self.candidate_identity,
            ),
            "classification": self.assessment.classification,
            "rebind_allowed": self.assessment.rebind_allowed,
            "integration_required": self.assessment.integration_required,
            "reconciliation_required": self.assessment.reconciliation_required,
            "index_action": self.assessment.index_action,
            "source_digest": self.assessment.candidate_digest,
            "candidate_path_disclosed": False,
            "source_effect": "read-only",
            "record_plans": [item.public_summary() for item in self.record_plans],
        }


@dataclass(frozen=True)
class SourceRebindResult:
    plan_id: str
    classification: str
    records: tuple[StoredRecord, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "classification": self.classification,
            "records": [record.public_summary() for record in self.records],
            "source_mutated": False,
        }


def candidate_binding(binding: SourceBinding, candidate_root: Path) -> SourceBinding:
    """Build a read-only candidate binding used only for discovery."""

    return SourceBinding(
        schema_version=binding.schema_version,
        binding_id=binding.binding_id,
        source_id=binding.source_id,
        source_kind=binding.source_kind,
        locator=SourceLocator("local-path", str(candidate_root.resolve(strict=False))),
        default_access=binding.default_access,
        capabilities=binding.capabilities,
        policy_refs=binding.policy_refs,
        revision=binding.revision,
    )


def prepare_source_rebind(
    store: LocalWorkspaceStore,
    binding: SourceBinding,
    candidate_root: Path,
    discovery: DiscoveryResult,
) -> SourceRebindPlan:
    """Plan a locator-only update after exact read-only identity verification."""

    if binding.locator.kind not in {"local-path", "unbound"} or binding.default_access != "read-only":
        raise SourceRebindError("rebind requires a read-only local or unbound binding")
    if "write" in binding.capabilities:
        raise SourceRebindError("rebind cannot use a write-capable source binding")
    root, _ = assert_external_source(candidate_root, store.data_root)
    if not root.is_dir() or root.is_symlink():
        raise SourceRebindError("candidate source must be an existing regular directory")
    if (
        binding.locator.kind == "local-path"
        and Path(binding.locator.value).resolve(strict=False) == root
    ):
        raise SourceRebindError("candidate source is already the active binding")
    binding_record = store.read("source-bindings", binding.binding_id)
    if binding_record is None or binding_record.revision != binding.revision:
        raise SourceRebindError("source binding revision changed before rebind")
    state_record = store.read("source-states", binding.binding_id)
    if state_record is None:
        raise SourceRebindError("rebind requires accepted source discovery state")
    state = parse_source_state(state_record.payload)
    if state.binding_revision != binding.revision:
        raise SourceRebindError("source state is stale for the current binding")
    if (
        discovery.binding_id != binding.binding_id
        or discovery.source_id != binding.source_id
        or discovery.binding_revision != binding.revision
    ):
        raise SourceRebindError("candidate discovery does not match source binding")
    expected_identity = source_identity_from_state(binding.source_id, state)
    discovered_identity = source_identity_from_discovery(discovery)
    assessment = classify_source_relocation(expected_identity, discovered_identity)
    if not assessment.rebind_allowed:
        raise SourceRebindError(
            f"candidate is classified as {assessment.classification}; locator-only rebind is blocked"
        )

    next_revision = binding.revision + 1
    binding_payload = dict(binding_record.payload)
    binding_payload["locator"] = {"kind": "local-path", "value": str(root)}
    binding_payload["revision"] = next_revision
    binding_plan = store.prepare_put(
        "source-bindings",
        binding.binding_id,
        binding_payload,
        expected_revision=binding_record.revision,
    )
    state_payload = source_state_from_discovery(discovery).as_payload()
    state_payload["binding_revision"] = next_revision
    state_plan = store.prepare_put(
        "source-states",
        binding.binding_id,
        state_payload,
        expected_revision=state_record.revision,
    )
    record_plans = (binding_plan, state_plan)
    identity = {
        "binding_id": binding.binding_id,
        "source_id": binding.source_id,
        "previous_binding_revision": binding.revision,
        "next_binding_revision": next_revision,
        "candidate_root_sha256": hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
        "source_identity": expected_identity.as_dict(),
        "relocation_assessment": assessment.public_summary(),
        "record_plan_ids": [item.mutation.plan_id for item in record_plans],
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SourceRebindPlan(
        plan_id=plan_id,
        binding_id=binding.binding_id,
        source_id=binding.source_id,
        previous_binding_revision=binding.revision,
        next_binding_revision=next_revision,
        candidate_root=root,
        expected_identity=expected_identity,
        candidate_identity=discovered_identity,
        assessment=assessment,
        record_plans=record_plans,
    )


def apply_source_rebind(
    store: LocalWorkspaceStore,
    plan: SourceRebindPlan,
    authorizations: Mapping[str, MutationAuthorization],
    verified_binding: SourceBinding,
    verified_discovery: DiscoveryResult,
) -> SourceRebindResult:
    """Apply only the approved locator and derived revision changes."""

    if Path(verified_binding.locator.value).resolve(strict=False) != plan.candidate_root:
        raise SourceRebindError("verified candidate path does not match exact plan")
    current_identity = source_identity_from_discovery(verified_discovery)
    if not identities_match(plan.expected_identity, current_identity):
        raise SourceRebindError("candidate source changed after rebind planning")
    for record_plan in plan.record_plans:
        store.assert_plan_current(record_plan)
        authorization = authorizations.get(record_plan.mutation.plan_id)
        if authorization is None or authorization.plan.plan_id != record_plan.mutation.plan_id:
            raise SourceRebindError("every rebind write requires matching authorization")
        if not authorization.dry_run_verified:
            raise SourceRebindError("every rebind write requires verified dry-run")
        if record_plan.mutation.approval_required and not authorization.approval_verified:
            raise SourceRebindError("source rebind requires user approval")
    records = tuple(
        store.apply_put(item, authorizations[item.mutation.plan_id])
        for item in plan.record_plans
    )
    return SourceRebindResult(plan.plan_id, plan.assessment.classification, records)

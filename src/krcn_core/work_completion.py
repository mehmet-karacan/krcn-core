"""Evidence-bound, approval-reusing Work Graph completion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, TYPE_CHECKING

from .json_documents import canonical_json_bytes
from .mutation_gate import (
    DryRunEvidence,
    MutationAuthorization,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)
from .orchestration_plan import TaskPlan
from .orchestration_verifier import TaskVerification, verification_subject_digest
from .work_graph import (
    WorkEvidence,
    WorkItem,
    _project_items,
    _write_projection,
    build_work_event,
    build_work_item,
    parse_work_event,
    parse_work_item,
    work_graph_index_path,
)
from .work_index import apply_work_index, prepare_work_index_from_items

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore, RecordWritePlan


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class WorkCompletionError(ValueError):
    """Raised when a Work Graph item lacks exact completion proof."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _dependency_snapshot(
    items: Sequence[WorkItem],
    target: WorkItem,
) -> tuple[str, tuple[str, ...]]:
    by_id = {item.work_item_id: item for item in items}
    outgoing = tuple(
        sorted(
            (relation.relation_type, relation.target_ref)
            for relation in target.relations
        )
    )
    incoming = tuple(
        sorted(
            (item.work_item_id, relation.relation_type)
            for item in items
            for relation in item.relations
            if relation.target_ref == target.work_item_id
            and relation.relation_type in {"depends-on", "blocks", "parent-of"}
        )
    )
    relevant_ids = {target.work_item_id} | {
        relation.target_ref for relation in target.relations
    } | {source for source, _ in incoming}
    missing = sorted(relevant_ids - set(by_id))
    if missing:
        raise WorkCompletionError("work completion relation target is missing")
    dependencies = tuple(
        sorted(
            relation.target_ref
            for relation in target.relations
            if relation.relation_type == "depends-on"
        )
    )
    if any(by_id[item_id].status not in {"completed", "archived"} for item_id in dependencies):
        raise WorkCompletionError("work completion dependency is not completed")
    snapshot = [
        {
            "work_item_id": item.work_item_id,
            "revision": item.revision,
            "work_digest": item.work_digest,
            "status": item.status,
        }
        for item in sorted(
            (by_id[item_id] for item_id in relevant_ids),
            key=lambda item: item.work_item_id,
        )
    ]
    return _digest(
        {
            "target_relations": outgoing,
            "incoming_dependencies": incoming,
            "relevant_items": snapshot,
        }
    ), tuple(sorted(relevant_ids))


@dataclass(frozen=True)
class WorkCompletionAttestation:
    attestation_id: str
    project_id: str
    work_item_id: str
    task_id: str
    task_plan_id: str
    authorization_id: str
    verification_id: str
    base_item_revision: int
    base_item_digest: str
    dependency_digest: str
    relevant_work_item_ids: tuple[str, ...]
    acceptance_subject_digests: tuple[str, ...]
    checkpoint_ids: tuple[str, ...]
    verifier_execution_identity_ids: tuple[str, ...]
    verification_evidence_digests: tuple[str, ...]
    attestation_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-completion-attestation.schema.json",
            "schema_version": 1,
            "attestation_id": self.attestation_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "task_id": self.task_id,
            "task_plan_id": self.task_plan_id,
            "authorization_id": self.authorization_id,
            "verification_id": self.verification_id,
            "base_item_revision": self.base_item_revision,
            "base_item_digest": self.base_item_digest,
            "dependency_digest": self.dependency_digest,
            "relevant_work_item_ids": list(self.relevant_work_item_ids),
            "acceptance_subject_digests": list(self.acceptance_subject_digests),
            "checkpoint_ids": list(self.checkpoint_ids),
            "verifier_execution_identity_ids": list(
                self.verifier_execution_identity_ids
            ),
            "verification_evidence_digests": list(
                self.verification_evidence_digests
            ),
            "status": "verified",
            "completion_allowed": True,
            "reversible": True,
            "attestation_digest": self.attestation_digest,
        }


def parse_work_completion_attestation(value: object) -> WorkCompletionAttestation:
    fields = {
        "schema_ref", "schema_version", "attestation_id", "project_id",
        "work_item_id", "task_id", "task_plan_id", "authorization_id",
        "verification_id", "base_item_revision", "base_item_digest",
        "dependency_digest", "relevant_work_item_ids",
        "acceptance_subject_digests", "checkpoint_ids",
        "verifier_execution_identity_ids", "verification_evidence_digests",
        "status", "completion_allowed", "reversible", "attestation_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise WorkCompletionError("work completion attestation fields are invalid")
    payload = dict(value)
    if (
        payload["schema_ref"] != "schemas/work-completion-attestation.schema.json"
        or payload["schema_version"] != 1
        or payload["status"] != "verified"
        or payload["completion_allowed"] is not True
        or payload["reversible"] is not True
    ):
        raise WorkCompletionError("work completion attestation state is invalid")
    for field in ("attestation_id", "project_id", "work_item_id", "task_id"):
        if not isinstance(payload[field], str) or not IDENTIFIER.fullmatch(payload[field]):
            raise WorkCompletionError("work completion attestation identity is invalid")
    for field in (
        "task_plan_id", "authorization_id", "verification_id",
        "base_item_digest", "dependency_digest", "attestation_digest",
    ):
        if not isinstance(payload[field], str) or not SHA256.fullmatch(payload[field]):
            raise WorkCompletionError("work completion attestation digest is invalid")
    revision = payload["base_item_revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkCompletionError("work completion base revision is invalid")
    lists: dict[str, tuple[str, ...]] = {}
    for field, pattern in (
        ("relevant_work_item_ids", IDENTIFIER),
        ("acceptance_subject_digests", SHA256),
        ("checkpoint_ids", SHA256),
        ("verifier_execution_identity_ids", SHA256),
        ("verification_evidence_digests", SHA256),
    ):
        candidate = payload[field]
        if (
            not isinstance(candidate, list)
            or not candidate
            or candidate != sorted(candidate)
            or len(candidate) != len(set(candidate))
            or any(not isinstance(item, str) or not pattern.fullmatch(item) for item in candidate)
        ):
            raise WorkCompletionError("work completion proof list is invalid")
        lists[field] = tuple(candidate)
    identity = dict(payload)
    digest = identity.pop("attestation_digest")
    if digest != _digest(identity):
        raise WorkCompletionError("work completion attestation digest does not match")
    return WorkCompletionAttestation(
        str(payload["attestation_id"]), str(payload["project_id"]),
        str(payload["work_item_id"]), str(payload["task_id"]),
        str(payload["task_plan_id"]), str(payload["authorization_id"]),
        str(payload["verification_id"]), int(revision),
        str(payload["base_item_digest"]), str(payload["dependency_digest"]),
        lists["relevant_work_item_ids"], lists["acceptance_subject_digests"],
        lists["checkpoint_ids"], lists["verifier_execution_identity_ids"],
        lists["verification_evidence_digests"], str(digest),
    )


def build_work_completion_attestation(
    store: "LocalWorkspaceStore",
    *,
    project_id: str,
    work_item_id: str,
    plan: TaskPlan,
    verification: TaskVerification,
) -> WorkCompletionAttestation:
    stored = store.read("work-items", work_item_id)
    if stored is None:
        raise WorkCompletionError("work completion target is missing")
    from .work_graph import parse_work_item

    item = parse_work_item(stored.payload)
    if item.project_id != project_id or item.status != "active":
        raise WorkCompletionError("automatic completion requires one active target item")
    if (
        verification.task_id != plan.task_id
        or verification.plan_id != plan.plan_id
        or verification.status != "verified"
        or not verification.completion_allowed
        or verification.failure_codes
    ):
        raise WorkCompletionError("task verification does not authorize completion")
    acceptance = tuple(
        sorted(
            verification_subject_digest("acceptance-criterion", criterion)
            for criterion in item.acceptance_criteria
        )
    )
    verified_acceptance = tuple(
        sorted(
            subject.subject_digest
            for subject in verification.subjects
            if subject.kind == "acceptance-criterion" and subject.passed
        )
    )
    if not acceptance or acceptance != verified_acceptance:
        raise WorkCompletionError("work acceptance criteria lack exact verifier proof")
    evidence_digests = tuple(
        sorted(
            evidence.evidence_digest
            for evidence in verification.evidence
            if evidence.passed and evidence.subject_digest in acceptance
        )
    )
    verifier_ids = tuple(
        sorted(
            identity.execution_identity_id
            for identity in verification.verifier_execution_identities
        )
    )
    if not verification.worker_checkpoint_ids or not verifier_ids or not evidence_digests:
        raise WorkCompletionError("work completion proof is incomplete")
    dependency_digest, relevant_ids = _dependency_snapshot(
        _project_items(store, project_id), item
    )
    payload = {
        "schema_ref": "schemas/work-completion-attestation.schema.json",
        "schema_version": 1,
        "attestation_id": f"{plan.task_id}-work-completion",
        "project_id": project_id,
        "work_item_id": work_item_id,
        "task_id": plan.task_id,
        "task_plan_id": plan.plan_id,
        "authorization_id": verification.authorization_id,
        "verification_id": verification.verification_id,
        "base_item_revision": item.revision,
        "base_item_digest": item.work_digest,
        "dependency_digest": dependency_digest,
        "relevant_work_item_ids": list(relevant_ids),
        "acceptance_subject_digests": list(acceptance),
        "checkpoint_ids": list(sorted(verification.worker_checkpoint_ids)),
        "verifier_execution_identity_ids": list(verifier_ids),
        "verification_evidence_digests": list(evidence_digests),
        "status": "verified",
        "completion_allowed": True,
        "reversible": True,
    }
    payload["attestation_digest"] = _digest(payload)
    return parse_work_completion_attestation(payload)


def persist_work_completion_attestation(
    store: "LocalWorkspaceStore",
    attestation: WorkCompletionAttestation,
) -> None:
    current = store.read("work-completion-attestations", attestation.attestation_id)
    if current is not None:
        if current.payload != attestation.as_dict():
            raise WorkCompletionError("work completion attestation conflicts")
        return
    write = store.prepare_put(
        "work-completion-attestations",
        attestation.attestation_id,
        attestation.as_dict(),
        expected_revision=0,
        project_id=attestation.project_id,
    )
    authorization = authorize_mutation(
        write.mutation,
        dry_run=DryRunEvidence(write.mutation.plan_id, True),
    )
    store.apply_put(write, authorization)


def validate_applied_work_completion(
    store: "LocalWorkspaceStore",
    attestation: WorkCompletionAttestation,
) -> WorkItem:
    """Return the completed target only when the attested revision was applied exactly."""

    stored = store.read("work-items", attestation.work_item_id)
    event_record = store.read(
        "work-events",
        f"{attestation.work_item_id}-r{attestation.base_item_revision + 1}",
    )
    if stored is None or event_record is None:
        raise WorkCompletionError("attested work completion is not applied")
    item = parse_work_item(stored.payload)
    event = parse_work_event(event_record.payload)
    expected_source = {
        "source_kind": "orchestrator",
        "source_ref": attestation.attestation_id,
    }
    evidence_ref = f"work-completion-attestation:{attestation.attestation_id}"
    if (
        item.project_id != attestation.project_id
        or item.status != "completed"
        or item.revision != attestation.base_item_revision + 1
        or item.provenance != expected_source
        or not any(
            evidence.reference == evidence_ref
            and evidence.digest == attestation.verification_id
            for evidence in item.evidence
        )
        or event.project_id != item.project_id
        or event.work_item_id != item.work_item_id
        or event.from_status != "active"
        or event.to_status != "completed"
        or event.item_revision != item.revision
        or event.item_digest != item.work_digest
        or event.provenance != expected_source
    ):
        raise WorkCompletionError("attested work completion binding is invalid")
    return item


@dataclass(frozen=True)
class WorkCompletionPlan:
    attestation: WorkCompletionAttestation
    item: WorkItem
    record_plan: "RecordWritePlan"
    event_plan: "RecordWritePlan"
    plan_id: str
    repo_root: Path

    @property
    def effect_plans(self):
        return (self.record_plan.mutation, self.event_plan.mutation)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-completion-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.item.project_id,
            "work_item_id": self.item.work_item_id,
            "from_status": "active",
            "to_status": "completed",
            "base_item_revision": self.attestation.base_item_revision,
            "base_item_digest": self.attestation.base_item_digest,
            "dependency_digest": self.attestation.dependency_digest,
            "attestation_id": self.attestation.attestation_id,
            "reopen_supported": True,
            "effect_plans": [effect.as_dict() for effect in self.effect_plans],
        }


def prepare_verified_work_completion(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    attestation: WorkCompletionAttestation,
) -> WorkCompletionPlan:
    attestation = parse_work_completion_attestation(attestation.as_dict())
    stored = store.read("work-items", attestation.work_item_id)
    if stored is None:
        raise WorkCompletionError("work completion target is missing")
    from .work_graph import parse_work_item

    current = parse_work_item(stored.payload)
    if (
        current.project_id != attestation.project_id
        or current.status != "active"
        or current.revision != attestation.base_item_revision
        or current.work_digest != attestation.base_item_digest
    ):
        raise WorkCompletionError("work completion target changed after verification")
    dependency_digest, relevant_ids = _dependency_snapshot(
        _project_items(store, current.project_id), current
    )
    if (
        dependency_digest != attestation.dependency_digest
        or relevant_ids != attestation.relevant_work_item_ids
    ):
        raise WorkCompletionError("work completion dependencies changed after verification")
    evidence = [entry.as_dict() for entry in current.evidence]
    evidence.append(
        WorkEvidence(
            "document",
            f"work-completion-attestation:{attestation.attestation_id}",
            attestation.verification_id,
            "Independent verification and completed checkpoints",
        ).as_dict()
    )
    arguments = current.as_dict()
    arguments.pop("schema_ref")
    arguments.pop("schema_version")
    arguments.pop("revision")
    arguments.pop("work_digest")
    arguments["status"] = "completed"
    arguments["evidence"] = evidence
    arguments["provenance"] = {
        "source_kind": "orchestrator",
        "source_ref": attestation.attestation_id,
    }
    completed = build_work_item(arguments, current.revision + 1)
    record_plan = store.prepare_put(
        "work-items", completed.work_item_id, completed.as_dict(),
        expected_revision=current.revision,
        project_id=current.project_id,
        approval_scope="verified-work-completion",
        completion_attestation=attestation.as_dict(),
    )
    event = build_work_event(completed, current.status)
    event_plan = store.prepare_put(
        "work-events", event.work_event_id, event.as_dict(),
        expected_revision=0,
        project_id=current.project_id,
        approval_scope="verified-work-completion",
        completion_attestation=attestation.as_dict(),
    )
    plan_id = _digest(
        {
            "attestation_digest": attestation.attestation_digest,
            "target_revision": current.revision,
            "target_digest": current.work_digest,
            "dependency_digest": dependency_digest,
            "effects": [effect.as_dict() for effect in (
                record_plan.mutation, event_plan.mutation
            )],
        }
    )
    return WorkCompletionPlan(
        attestation, completed, record_plan, event_plan, plan_id, repo_root.resolve()
    )


def apply_verified_work_completion(
    store: "LocalWorkspaceStore",
    ownership: OwnershipResolver,
    plan: WorkCompletionPlan,
) -> dict[str, object]:
    stored = store.read("work-items", plan.item.work_item_id)
    if stored is None:
        raise WorkCompletionError("work completion target is missing")
    from .work_graph import parse_work_item

    current = parse_work_item(stored.payload)
    if (
        current.revision != plan.attestation.base_item_revision
        or current.work_digest != plan.attestation.base_item_digest
    ):
        raise WorkCompletionError("work completion target changed before apply")
    dependency_digest, relevant_ids = _dependency_snapshot(
        _project_items(store, plan.item.project_id), current
    )
    if (
        dependency_digest != plan.attestation.dependency_digest
        or relevant_ids != plan.attestation.relevant_work_item_ids
    ):
        raise WorkCompletionError("work completion dependencies changed before apply")
    authorizations: dict[str, MutationAuthorization] = {
        effect.plan_id: authorize_mutation(
            effect, dry_run=DryRunEvidence(effect.plan_id, True)
        )
        for effect in plan.effect_plans
    }
    stored_item = store.apply_put(
        plan.record_plan, authorizations[plan.record_plan.mutation.plan_id]
    )
    store.apply_put(
        plan.event_plan, authorizations[plan.event_plan.mutation.plan_id]
    )
    derived = _refresh_work_completion_indexes(
        plan.repo_root, store, ownership, plan.item.project_id
    )
    return {
        "plan": plan.public_summary(),
        "project_id": plan.item.project_id,
        "work_item_id": plan.item.work_item_id,
        "record_revision": stored_item.revision,
        "status": "completed",
        "attestation_id": plan.attestation.attestation_id,
        **derived,
        "approval_reused": True,
        "second_approval_required": False,
        "reopen_supported": True,
        "no_op": False,
    }


def _refresh_work_completion_indexes(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: OwnershipResolver,
    project_id: str,
) -> dict[str, object]:
    items = _project_items(store, project_id)
    graph_digest = _digest(
        [item.as_dict() for item in sorted(items, key=lambda item: item.work_item_id)]
    )
    projection_path = work_graph_index_path(store.data_root, project_id)
    projection = plan_mutation(
        ownership,
        operation="update" if projection_path.exists() else "create",
        target_ref=".krcn/" + projection_path.relative_to(store.data_root).as_posix(),
        expected_ownership="derived",
        change_digest=graph_digest,
        reversible=True,
    )
    authorize_mutation(
        projection, dry_run=DryRunEvidence(projection.plan_id, True)
    )
    _write_projection(projection_path, items, graph_digest)
    readable = prepare_work_index_from_items(
        repo_root,
        store,
        ownership,
        project_id,
        items,
        graph_digest,
    )
    readable_authorization = (
        None
        if readable.mutation is None
        else authorize_mutation(
            readable.mutation,
            dry_run=DryRunEvidence(readable.mutation.plan_id, True),
        )
    )
    readable_result = apply_work_index(
        repo_root,
        store,
        ownership,
        readable,
        readable_authorization,
        expected_plan_id=readable.plan_id,
    )
    return {
        "graph_digest": graph_digest,
        "projection_updated": True,
        "readable_index": readable_result,
    }


def reconcile_applied_work_completion(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: OwnershipResolver,
    attestation: WorkCompletionAttestation,
) -> dict[str, object]:
    """Repair rebuildable indexes and resume after an interrupted terminal transition."""

    item = validate_applied_work_completion(store, attestation)
    derived = _refresh_work_completion_indexes(
        repo_root, store, ownership, item.project_id
    )
    return {
        "project_id": item.project_id,
        "work_item_id": item.work_item_id,
        "record_revision": item.revision,
        "status": "completed",
        "attestation_id": attestation.attestation_id,
        **derived,
        "approval_reused": True,
        "second_approval_required": False,
        "reopen_supported": True,
        "no_op": True,
        "reconciled": True,
    }

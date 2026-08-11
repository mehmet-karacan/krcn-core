"""Revision-aware source rescan and controlled metadata updates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from .discovery import DiscoveryResult, FileEvidence
from .local_store import LocalWorkspaceStore, RecordWritePlan, StoredRecord
from .mutation_gate import MutationAuthorization
from .source_bindings import SourceBinding
from .source_state import SourceState, parse_source_state, source_state_from_discovery


class RescanError(ValueError):
    """Raised when source rescan cannot be planned or applied safely."""


@dataclass(frozen=True)
class RescanChanges:
    added: tuple[str, ...]
    modified: tuple[str, ...]
    removed: tuple[str, ...]
    technologies_added: tuple[str, ...]
    technologies_removed: tuple[str, ...]
    binding_revision_changed: bool

    @property
    def changed(self) -> bool:
        return any(
            (
                self.added,
                self.modified,
                self.removed,
                self.technologies_added,
                self.technologies_removed,
            )
        ) or self.binding_revision_changed

    def as_dict(self) -> dict[str, object]:
        return {
            "added": list(self.added),
            "modified": list(self.modified),
            "removed": list(self.removed),
            "technologies_added": list(self.technologies_added),
            "technologies_removed": list(self.technologies_removed),
            "binding_revision_changed": self.binding_revision_changed,
        }


@dataclass(frozen=True)
class RescanPlan:
    plan_id: str
    binding_id: str
    source_id: str
    previous_root_digest: str | None
    current_root_digest: str
    changes: RescanChanges
    record_plans: tuple[RecordWritePlan, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "binding_id": self.binding_id,
            "source_id": self.source_id,
            "previous_root_digest": self.previous_root_digest,
            "current_root_digest": self.current_root_digest,
            "changes": self.changes.as_dict(),
            "record_plans": [
                {
                    "record_type": item.record_type,
                    "record_id": item.record_id,
                    "mutation_plan_id": item.mutation.plan_id,
                    "ownership": item.mutation.ownership,
                }
                for item in self.record_plans
            ],
        }


@dataclass(frozen=True)
class RescanResult:
    plan_id: str
    records: tuple[StoredRecord, ...]


def _file_map(files: tuple[FileEvidence, ...]) -> dict[str, FileEvidence]:
    return {item.relative_path: item for item in files}


def compare_source_state(
    previous: SourceState | None,
    current: DiscoveryResult,
) -> RescanChanges:
    previous_files = _file_map(previous.files) if previous else {}
    current_files = _file_map(current.files)
    previous_paths = set(previous_files)
    current_paths = set(current_files)
    modified = tuple(
        sorted(
            path
            for path in previous_paths & current_paths
            if previous_files[path] != current_files[path]
        )
    )
    previous_technologies = set(previous.technologies) if previous else set()
    current_technologies = set(current.technologies)
    return RescanChanges(
        added=tuple(sorted(current_paths - previous_paths)),
        modified=modified,
        removed=tuple(sorted(previous_paths - current_paths)),
        technologies_added=tuple(sorted(current_technologies - previous_technologies)),
        technologies_removed=tuple(sorted(previous_technologies - current_technologies)),
        binding_revision_changed=bool(
            previous and previous.binding_revision != current.binding_revision
        ),
    )


def _project_payload_with_discovered_technologies(
    payload: Mapping[str, object],
    technologies: tuple[str, ...],
) -> dict[str, object]:
    updated = dict(payload)
    existing = payload.get("technologies", [])
    if not isinstance(existing, list):
        raise RescanError("project technologies must be a list")
    manual = [
        item
        for item in existing
        if isinstance(item, dict) and item.get("category") != "discovered"
    ]
    discovered = [
        {"name": technology, "category": "discovered"}
        for technology in technologies
    ]
    updated["technologies"] = [*manual, *discovered]
    return updated


def prepare_rescan(
    store: LocalWorkspaceStore,
    binding: SourceBinding,
    discovery: DiscoveryResult,
) -> RescanPlan:
    """Compare discovery with derived state and prepare only required writes."""

    if binding.source_kind != "project":
        raise RescanError("project rescan requires a project source binding")
    if (
        discovery.binding_id != binding.binding_id
        or discovery.source_id != binding.source_id
        or discovery.binding_revision != binding.revision
    ):
        raise RescanError("discovery result does not match source binding")
    project_record = store.read("projects", binding.source_id)
    if project_record is None:
        raise RescanError("project record is not registered")
    state_record = store.read("source-states", binding.binding_id)
    previous_state = parse_source_state(state_record.payload) if state_record else None
    current_state = source_state_from_discovery(discovery)
    changes = compare_source_state(previous_state, discovery)
    record_plans: list[RecordWritePlan] = []

    desired_project = _project_payload_with_discovered_technologies(
        project_record.payload,
        discovery.technologies,
    )
    if desired_project != dict(project_record.payload):
        record_plans.append(
            store.prepare_put(
                "projects",
                binding.source_id,
                desired_project,
                expected_revision=project_record.revision,
            )
        )
    if (
        previous_state is None
        or changes.changed
        or previous_state.root_digest != discovery.root_digest
    ):
        record_plans.append(
            store.prepare_put(
                "source-states",
                binding.binding_id,
                current_state.as_payload(),
                expected_revision=state_record.revision if state_record else 0,
            )
        )
    identity = {
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "previous_root_digest": previous_state.root_digest if previous_state else None,
        "current_root_digest": discovery.root_digest,
        "changes": changes.as_dict(),
        "record_plan_ids": [item.mutation.plan_id for item in record_plans],
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RescanPlan(
        plan_id=plan_id,
        binding_id=binding.binding_id,
        source_id=binding.source_id,
        previous_root_digest=previous_state.root_digest if previous_state else None,
        current_root_digest=discovery.root_digest,
        changes=changes,
        record_plans=tuple(record_plans),
    )


def apply_rescan(
    store: LocalWorkspaceStore,
    plan: RescanPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> RescanResult:
    """Apply all approved plans, committing derived state after project metadata."""

    for record_plan in plan.record_plans:
        store.assert_plan_current(record_plan)
        authorization = authorizations.get(record_plan.mutation.plan_id)
        if authorization is None or authorization.plan.plan_id != record_plan.mutation.plan_id:
            raise RescanError("every rescan write requires matching authorization")
        if not authorization.dry_run_verified:
            raise RescanError("every rescan write requires verified dry-run")
        if record_plan.mutation.approval_required and not authorization.approval_verified:
            raise RescanError("user-data rescan write requires user approval")

    ordered = sorted(
        plan.record_plans,
        key=lambda item: 1 if item.record_type == "source-states" else 0,
    )
    records = tuple(
        store.apply_put(item, authorizations[item.mutation.plan_id])
        for item in ordered
    )
    return RescanResult(plan_id=plan.plan_id, records=records)

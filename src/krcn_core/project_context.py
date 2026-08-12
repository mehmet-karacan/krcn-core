"""Resolve one registered project from a working directory or user request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from .information_records import parse_information_record, record_is_stale
from .local_store import LocalWorkspaceStore, StoredRecord
from .orchestration_state import parse_orchestration_handoff
from .project_integration_state import parse_project_integration_state
from .source_code_index import source_code_index_summary
from .source_bindings import SourceBinding, parse_source_binding
from .source_state import parse_source_state
from .work_graph import ACTIVE_STATUSES, parse_work_item


ACTIVE_TASK_STATUSES = {
    "planned",
    "awaiting-approval",
    "authorized",
    "running",
    "verifying",
    "failed",
    "interrupted",
    "blocked",
}


class ProjectContextError(ValueError):
    """Raised when current-project selection is invalid or ambiguous."""


@dataclass(frozen=True)
class ProjectContextMatch:
    project: StoredRecord
    bindings: tuple[SourceBinding, ...]
    selection_basis: str

    def public_summary(self, store: LocalWorkspaceStore) -> dict[str, object]:
        project = self.project
        source_states = []
        for binding in self.bindings:
            state = store.read("source-states", binding.binding_id)
            if state is not None:
                source_states.append(
                    {
                        "binding_id": binding.binding_id,
                        "record_revision": state.revision,
                        "binding_revision": state.payload["binding_revision"],
                        "root_digest": state.payload["root_digest"],
                        "file_count": len(state.payload["files"]),
                        "technologies": list(state.payload["technologies"]),
                    }
                )
        return {
            "schema_ref": "schemas/project-context-result.schema.json",
            "schema_version": 1,
            "matched": True,
            "selection_basis": self.selection_basis,
            "project": {
                "project_id": project.record_id,
                "name": project.payload.get("name"),
                "status": project.payload.get("status"),
                "record_revision": project.revision,
            },
            "source_bindings": [binding.public_summary() for binding in self.bindings],
            "source_states": source_states,
            "paths_disclosed": False,
        }


def _project_bindings(
    store: LocalWorkspaceStore,
    project: StoredRecord,
) -> tuple[SourceBinding, ...]:
    refs = project.payload.get("source_refs", [])
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise ProjectContextError("project source references are invalid")
    bindings = []
    for binding_id in refs:
        record = store.read("source-bindings", binding_id)
        if record is None:
            raise ProjectContextError("project source binding is missing")
        bindings.append(parse_source_binding(record.payload))
    return tuple(bindings)


def _mentioned_projects(
    projects: tuple[StoredRecord, ...],
    request_text: str,
) -> tuple[StoredRecord, ...]:
    text = request_text.casefold()
    matches = []
    for project in projects:
        candidates = {project.record_id, str(project.payload.get("name", "")).strip()}
        if any(
            candidate
            and re.search(
                rf"(?<![\w-]){re.escape(candidate.casefold())}(?![\w-])",
                text,
            )
            for candidate in candidates
        ):
            matches.append(project)
    return tuple(matches)


def _explicit_projects(
    projects: tuple[StoredRecord, ...],
    project_ref: str,
) -> tuple[StoredRecord, ...]:
    reference = project_ref.strip().casefold()
    if not reference:
        raise ProjectContextError("project reference must be non-empty")
    return tuple(
        project
        for project in projects
        if reference
        in {
            project.record_id.casefold(),
            str(project.payload.get("name", "")).strip().casefold(),
        }
    )


def _path_depth(path: Path) -> int:
    return len(path.parts)


def _path_contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _working_directory_projects(
    store: LocalWorkspaceStore,
    projects: tuple[StoredRecord, ...],
    working_directory: Path,
) -> tuple[StoredRecord, ...]:
    if not working_directory.is_absolute():
        raise ProjectContextError("working directory must be absolute")
    resolved_working = working_directory.resolve(strict=False)
    matches: list[tuple[int, StoredRecord]] = []
    for project in projects:
        roots = []
        for binding in _project_bindings(store, project):
            if binding.source_kind != "project" or binding.locator.kind != "local-path":
                continue
            root = Path(binding.locator.value)
            if not root.is_absolute():
                continue
            resolved_root = root.resolve(strict=False)
            if _path_contains(resolved_root, resolved_working):
                roots.append(resolved_root)
        if roots:
            matches.append((max(_path_depth(root) for root in roots), project))
    if not matches:
        return ()
    deepest = max(depth for depth, _ in matches)
    return tuple(project for depth, project in matches if depth == deepest)


def _single_match(
    store: LocalWorkspaceStore,
    matches: tuple[StoredRecord, ...],
    basis: str,
) -> ProjectContextMatch | None:
    if not matches:
        return None
    project_ids = {project.record_id for project in matches}
    if len(project_ids) != 1:
        raise ProjectContextError(
            "project selection is ambiguous: " + ", ".join(sorted(project_ids))
        )
    project = matches[0]
    return ProjectContextMatch(project, _project_bindings(store, project), basis)


def resolve_current_project(
    store: LocalWorkspaceStore,
    *,
    working_directory: Path,
    project_ref: str | None = None,
    request_text: str | None = None,
) -> ProjectContextMatch | None:
    """Select a project without disclosing local binding paths."""

    projects = store.list_records("projects")
    if project_ref is not None:
        match = _single_match(
            store,
            _explicit_projects(projects, project_ref),
            "explicit-project",
        )
        if match is None:
            raise ProjectContextError("referenced project is not registered")
        return match
    if request_text is not None and request_text.strip():
        mentioned = _mentioned_projects(projects, request_text)
        if mentioned:
            return _single_match(store, mentioned, "request-mention")
    return _single_match(
        store,
        _working_directory_projects(store, projects, working_directory),
        "working-directory",
    )


def unmatched_project_context() -> dict[str, object]:
    return {
        "schema_ref": "schemas/project-context-result.schema.json",
        "schema_version": 1,
        "matched": False,
        "selection_basis": "none",
        "project": None,
        "source_bindings": [],
        "source_states": [],
        "paths_disclosed": False,
    }


def _information_summary(
    store: LocalWorkspaceStore,
    project_id: str,
    binding_ids: set[str],
) -> dict[str, int]:
    subject_refs = {f"project:{project_id}", f"source:{project_id}"}
    subject_refs.update(f"source:{binding_id}" for binding_id in binding_ids)
    records = []
    for collection in ("authoritative-sources", "knowledge", "memory"):
        for stored in store.list_records(collection):
            record = parse_information_record(dict(stored.payload))
            if any(
                record.subject_ref == subject_ref
                or record.subject_ref.startswith(f"{subject_ref}/")
                for subject_ref in subject_refs
            ):
                records.append(record)
    current_revisions = {
        record.subject_ref: (
            str(record.payload["source_revision_id"]),
            str(record.payload["source_digest"]),
        )
        for record in records
        if record.information_class == "authoritative-source"
        and record.lifecycle == "current"
    }
    stale = [
        record
        for record in records
        if record.lifecycle in {"stale", "superseded", "archived"}
        or record_is_stale(record, current_revisions)
    ]
    return {
        "record_count": len(records),
        "current_count": len(records) - len(stale),
        "stale_count": len(stale),
    }


def _work_summary(
    store: LocalWorkspaceStore,
    project_id: str,
    binding_ids: set[str],
) -> dict[str, object]:
    context_refs = {project_id, f"project:{project_id}"}
    context_refs.update(binding_ids)
    context_refs.update(f"source:{binding_id}" for binding_id in binding_ids)
    handoffs = []
    for stored in store.list_records("orchestration-handoffs"):
        handoff = parse_orchestration_handoff(stored.payload)
        if context_refs.intersection(handoff.context_refs):
            handoffs.append(handoff)
    handoffs.sort(
        key=lambda item: (
            item.status not in ACTIVE_TASK_STATUSES,
            -item.revision,
            item.task_id,
        )
    )
    public_handoffs = [
        {
            "task_id": handoff.task_id,
            "status": handoff.status,
            "completed_step_ids": list(handoff.completed_step_ids),
            "pending_step_ids": list(handoff.pending_step_ids),
            "approval_triggers": list(handoff.approval_triggers),
            "failure_codes": list(handoff.failure_codes),
            "resume_token": handoff.resume_token,
            "revision": handoff.revision,
        }
        for handoff in handoffs[:5]
    ]
    work_items = [
        parse_work_item(record.payload)
        for record in store.list_records("work-items")
        if record.payload.get("project_id") == project_id
    ]
    work_items.sort(
        key=lambda item: (
            item.status not in ACTIVE_STATUSES,
            item.work_item_id,
        )
    )
    return {
        "active_task_count": sum(
            item.status in ACTIVE_STATUSES for item in work_items
        ),
        "historical_task_count": sum(
            item.status not in ACTIVE_STATUSES for item in work_items
        ),
        "items": [
            {
                "work_item_id": item.work_item_id,
                "work_type": item.work_type,
                "title": item.title,
                "status": item.status,
                "revision": item.revision,
                "evidence_count": len(item.evidence),
            }
            for item in work_items[:10]
        ],
        "active_orchestration_count": sum(
            handoff.status in ACTIVE_TASK_STATUSES for handoff in handoffs
        ),
        "handoffs": public_handoffs,
        "authoritative_status": True,
    }


def _integration_summary(
    store: LocalWorkspaceStore,
    project_id: str,
) -> dict[str, object]:
    stored = store.read("project-integrations", project_id)
    modified = store.record_mtime_ns("project-integrations", project_id)
    if stored is None or modified is None:
        return {
            "status": "incomplete",
            "last_scan_mode": None,
            "last_successful_scan_at": None,
            "next_automatic_scan_at": None,
            "automatic_scan_due": True,
            "stages": {},
            "role_refs": [],
            "skill_refs": [],
        }
    state = parse_project_integration_state(stored.payload)
    last_scan = datetime.fromtimestamp(modified / 1_000_000_000, timezone.utc)
    next_scan = last_scan + timedelta(hours=state.freshness_hours)
    return {
        "status": "complete",
        "last_scan_mode": state.scan_mode,
        "last_scan_reason": state.scan_reason,
        "scan_sequence": state.scan_sequence,
        "last_successful_scan_at": last_scan.isoformat(),
        "next_automatic_scan_at": next_scan.isoformat(),
        "automatic_scan_due": datetime.now(timezone.utc) >= next_scan,
        "freshness_hours": state.freshness_hours,
        "embedding_profile_id": state.embedding_profile_id,
        "stages": dict(state.stages),
        "role_refs": list(state.role_refs),
        "skill_refs": list(state.skill_refs),
    }


def build_project_resume_summary(
    store: LocalWorkspaceStore,
    match: ProjectContextMatch,
    repo_root: Path | None = None,
) -> dict[str, object]:
    """Build a compact, path-redacted summary for another client to resume work."""

    context = match.public_summary(store)
    binding_ids = {binding.binding_id for binding in match.bindings}
    information = _information_summary(store, match.project.record_id, binding_ids)
    work = _work_summary(store, match.project.record_id, binding_ids)
    integration = _integration_summary(store, match.project.record_id)
    source_code_index: dict[str, object] = {
        "status": "unknown",
        "project_id": match.project.record_id,
        "paths_disclosed": False,
    }
    if repo_root is not None and match.bindings:
        state_record = store.read("source-states", match.bindings[0].binding_id)
        state = parse_source_state(state_record.payload) if state_record else None
        source_code_index = source_code_index_summary(
            repo_root,
            store.data_root,
            match.project.record_id,
            binding_id=match.bindings[0].binding_id,
            source_digest=state.root_digest if state else None,
        )
    states = context["source_states"]
    assert isinstance(states, list)
    indexed_files = sum(int(state["file_count"]) for state in states)
    next_actions = []
    if not states:
        next_actions.append("rescan-project-source")
    if information["record_count"] == 0:
        next_actions.append("extract-project-information")
    if integration["status"] != "complete":
        next_actions.append("complete-project-integration")
    elif integration["automatic_scan_due"]:
        next_actions.append("refresh-project-integration")
    if source_code_index["status"] not in {"current", "unknown"}:
        next_actions.append("rebuild-source-code-index")
    if work["active_task_count"] == 0:
        next_actions.append("no-active-task-start-from-user-request")
    return {
        **context,
        "resume": {
            "project_registered": True,
            "source_state_count": len(states),
            "indexed_source_file_count": indexed_files,
            "information": information,
            "integration": integration,
            "source_code_index": source_code_index,
            "work": work,
            "next_actions": next_actions,
        },
    }

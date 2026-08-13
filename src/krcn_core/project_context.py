"""Resolve one registered project from a working directory or user request."""

from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from .agent_runtime import AgentRuntimeQueue, load_scheduler_policy
from .discovery import DiscoveryResult
from .information_records import parse_information_record, record_is_stale
from .json_documents import canonical_json_bytes
from .local_store import LocalWorkspaceStore, StoredRecord
from .orchestration_state import parse_orchestration_handoff
from .project_capability_profile import (
    ProjectCapabilityProfileError,
    parse_project_capability_profile,
    project_capability_public_summary,
    project_capability_profile_is_current,
)
from .project_integration_state import parse_project_integration_state
from .source_bindings import SourceBinding, parse_source_binding
from .source_code_index import source_code_index_summary
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
    if reference.isdigit():
        position = int(reference)
        ordered = tuple(sorted(projects, key=lambda project: project.record_id))
        if 1 <= position <= len(ordered):
            return (ordered[position - 1],)
        return ()
    normalized_reference = _search_key(reference)
    return tuple(
        project
        for project in projects
        if normalized_reference
        in {
            _search_key(project.record_id),
            _search_key(project.payload.get("name", "")),
        }
    )


def _search_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(character for character in normalized if character.isalnum())


def _project_integration_status(
    store: LocalWorkspaceStore,
    project_id: str,
) -> str:
    stored = store.read("project-integrations", project_id)
    if stored is None:
        return "not-integrated"
    try:
        state = parse_project_integration_state(stored.payload)
    except ValueError:
        return "invalid"
    if any(value != "complete" for value in state.stages.values()):
        return "incomplete"
    modified = store.record_mtime_ns("project-integrations", project_id)
    if modified is None:
        return "invalid"
    last_scan = datetime.fromtimestamp(modified / 1_000_000_000, timezone.utc)
    if datetime.now(timezone.utc) >= last_scan + timedelta(hours=state.freshness_hours):
        return "stale"
    return "complete"


def _iso_timestamp(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).isoformat()


def project_navigation_menu(store: LocalWorkspaceStore) -> dict[str, object]:
    """Return a stable, path-redacted project menu with work activity counts."""

    projects = tuple(sorted(
        store.list_records("projects"), key=lambda project: project.record_id,
    ))
    work_records = tuple(store.list_records("work-items"))
    result = []
    for position, project in enumerate(projects, 1):
        project_id = project.record_id
        scoped_work = tuple(
            (record, parse_work_item(record.payload))
            for record in work_records
            if record.payload.get("project_id") == project_id
        )
        counts = {
            "requests": {"active": 0, "historical": 0, "total": 0},
            "defects": {"active": 0, "historical": 0, "total": 0},
            "tasks": {"active": 0, "historical": 0, "total": 0},
        }
        activity_candidates: list[tuple[int, str]] = []
        project_modified = store.record_mtime_ns("projects", project_id)
        if project_modified is not None:
            activity_candidates.append((project_modified, "project"))
        integration_modified = store.record_mtime_ns(
            "project-integrations", project_id,
        )
        if integration_modified is not None:
            activity_candidates.append((integration_modified, "integration"))
        source_refs = project.payload.get("source_refs", [])
        if isinstance(source_refs, list):
            for source_ref in source_refs:
                if isinstance(source_ref, str):
                    source_modified = store.record_mtime_ns(
                        "source-states", source_ref,
                    )
                    if source_modified is not None:
                        activity_candidates.append((source_modified, "source"))
        for record, item in scoped_work:
            group = (
                "requests" if item.work_type == "request"
                else "defects" if item.work_type == "defect"
                else "tasks"
            )
            lifecycle = "active" if item.status in ACTIVE_STATUSES else "historical"
            counts[group][lifecycle] += 1
            counts[group]["total"] += 1
            modified = store.record_mtime_ns("work-items", record.record_id)
            if modified is not None:
                activity_candidates.append((modified, group[:-1]))
        document_manifest = (
            store.data_root / "projects" / project_id / "local-data"
            / "work-documents" / "_krcn" / "import-manifest.json"
        )
        if document_manifest.exists():
            if document_manifest.is_symlink() or not document_manifest.is_file():
                raise ProjectContextError("work document manifest must be regular")
            activity_candidates.append(
                (document_manifest.stat().st_mtime_ns, "work-documents")
            )
        latest = max(activity_candidates, default=(0, "none"))
        active_total = sum(value["active"] for value in counts.values())
        historical_total = sum(value["historical"] for value in counts.values())
        result.append({
            "position": position,
            "project_id": project_id,
            "name": project.payload.get("name"),
            "status": project.payload.get("status"),
            "revision": project.revision,
            "integration_status": _project_integration_status(store, project_id),
            "work_counts": {
                **counts,
                "active_total": active_total,
                "historical_total": historical_total,
                "total": active_total + historical_total,
            },
            "last_updated_at": _iso_timestamp(latest[0] or None),
            "last_update_scope": latest[1],
        })
    selection_digest = hashlib.sha256(canonical_json_bytes([
        {
            "position": item["position"],
            "project_id": item["project_id"],
            "revision": item["revision"],
            "last_updated_at": item["last_updated_at"],
        }
        for item in result
    ])).hexdigest()
    return {
        "projects": result,
        "project_count": len(result),
        "selection_digest": selection_digest,
        "selection_is_read_only": True,
        "selection_grants_authority": False,
        "paths_disclosed": False,
    }


def suggest_projects(
    store: LocalWorkspaceStore,
    reference: str,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Suggest registered projects without silently choosing a fuzzy match."""

    query = _search_key(reference)
    menu = project_navigation_menu(store)
    projects = menu["projects"]
    assert isinstance(projects, list)
    scored = []
    for project in projects:
        candidate = _search_key(project["project_id"])
        name = _search_key(project.get("name", ""))
        score = max(
            difflib.SequenceMatcher(a=query, b=candidate).ratio(),
            difflib.SequenceMatcher(a=query, b=name).ratio(),
        )
        scored.append((score, project))
    return [
        {
            "position": project["position"],
            "project_id": project["project_id"],
            "name": project["name"],
            "similarity": round(score, 3),
        }
        for score, project in sorted(
            scored, key=lambda value: (-value[0], value[1]["project_id"]),
        )[:limit]
        if score >= 0.45
    ]


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
        basis = (
            "ordinal-project"
            if project_ref.strip().isdigit()
            else "explicit-project"
        )
        match = _single_match(
            store,
            _explicit_projects(projects, project_ref),
            basis,
        )
        if match is None:
            return None
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
    repo_root: Path | None = None,
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
        (
            parse_work_item(record.payload),
            store.record_mtime_ns("work-items", record.record_id),
        )
        for record in store.list_records("work-items")
        if record.payload.get("project_id") == project_id
    ]
    work_items.sort(
        key=lambda value: (
            value[0].status not in ACTIVE_STATUSES,
            -(value[1] or 0),
            value[0].work_item_id,
        )
    )
    work_counts = {
        "requests": {"active": 0, "historical": 0, "total": 0},
        "defects": {"active": 0, "historical": 0, "total": 0},
        "tasks": {"active": 0, "historical": 0, "total": 0},
    }
    for item, _ in work_items:
        group = (
            "requests" if item.work_type == "request"
            else "defects" if item.work_type == "defect"
            else "tasks"
        )
        lifecycle = (
            "active" if item.status in ACTIVE_STATUSES else "historical"
        )
        work_counts[group][lifecycle] += 1
        work_counts[group]["total"] += 1
    active_total = sum(value["active"] for value in work_counts.values())
    historical_total = sum(
        value["historical"] for value in work_counts.values()
    )
    runtime_queue: dict[str, object] = {
        "counts": {},
        "active_lease_count": 0,
        "pending_projection_count": 0,
        "integrity_verified": True,
    }
    if repo_root is not None:
        runtime_status = AgentRuntimeQueue(
            store.data_root,
            project_id,
            load_scheduler_policy(repo_root),
        ).status()
        runtime_queue = {
            "counts": runtime_status["counts"],
            "active_lease_count": runtime_status["active_lease_count"],
            "pending_projection_count": runtime_status.get(
                "pending_projection_count", 0
            ),
            "integrity_verified": runtime_status["integrity_verified"],
        }
    return {
        "active_task_count": active_total,
        "historical_task_count": historical_total,
        "work_counts": {
            **work_counts,
            "active_total": active_total,
            "historical_total": historical_total,
            "total": active_total + historical_total,
        },
        "items": [
            {
                "work_item_id": item.work_item_id,
                "work_type": item.work_type,
                "title": item.title,
                "status": item.status,
                "revision": item.revision,
                "evidence_count": len(item.evidence),
                "last_updated_at": _iso_timestamp(modified),
            }
            for item, modified in work_items[:10]
        ],
        "active_orchestration_count": sum(
            handoff.status in ACTIVE_TASK_STATUSES for handoff in handoffs
        ),
        "handoffs": public_handoffs,
        "authoritative_status": True,
        "runtime_queue": runtime_queue,
    }


def _integration_summary(
    store: LocalWorkspaceStore,
    project_id: str,
    repo_root: Path | None = None,
    binding: SourceBinding | None = None,
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
            "capability_profile": {"status": "missing", "paths_disclosed": False},
        }
    state = parse_project_integration_state(stored.payload)
    capability_summary: dict[str, object] = {
        "status": "missing",
        "paths_disclosed": False,
    }
    capability_record = store.read("knowledge", f"{project_id}-capabilities")
    if capability_record is not None:
        try:
            information = parse_information_record(capability_record.payload)
            profile = parse_project_capability_profile(
                information.payload.get("profile")
            )
            profile_current = False
            if repo_root is not None and binding is not None:
                source_state_record = store.read("source-states", binding.binding_id)
                source_state = (
                    parse_source_state(source_state_record.payload)
                    if source_state_record
                    else None
                )
                if source_state is not None:
                    discovery = DiscoveryResult(
                        binding.binding_id,
                        binding.source_id,
                        binding.revision,
                        source_state.root_digest,
                        source_state.files,
                        source_state.technologies,
                        {
                            "blocked": 0,
                            "symlink": 0,
                            "too_large": 0,
                            "unstable": 0,
                            "unreadable": 0,
                        },
                    )
                    profile_current = project_capability_profile_is_current(
                        repo_root,
                        profile,
                        project_id,
                        binding,
                        discovery,
                    )
            capability_summary = {
                "status": "current" if profile_current else "stale",
                **project_capability_public_summary(profile),
            }
        except (ProjectCapabilityProfileError, ValueError):
            capability_summary = {"status": "stale", "paths_disclosed": False}
    last_scan = datetime.fromtimestamp(modified / 1_000_000_000, timezone.utc)
    next_scan = last_scan + timedelta(hours=state.freshness_hours)
    return {
        "status": (
            "complete"
            if capability_summary["status"] == "current"
            else "incomplete"
        ),
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
        "capability_profile": capability_summary,
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
    work = _work_summary(
        store,
        match.project.record_id,
        binding_ids,
        repo_root,
    )
    integration = _integration_summary(
        store,
        match.project.record_id,
        repo_root,
        match.bindings[0] if len(match.bindings) == 1 else None,
    )
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
            binding_revision=match.bindings[0].revision,
            source_digest=state.root_digest if state else None,
        )
    states = context["source_states"]
    assert isinstance(states, list)
    indexed_files = (
        int(source_code_index.get("file_count", 0))
        if source_code_index.get("status") == "current"
        else 0
    )
    next_actions = []
    if not states:
        next_actions.append("rescan-project-source")
    if information["record_count"] == 0:
        next_actions.append("extract-project-information")
    if integration["status"] != "complete":
        next_actions.append("complete-project-integration")
        if integration["capability_profile"]["status"] != "current":
            next_actions.append("refresh-project-capability-profile")
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

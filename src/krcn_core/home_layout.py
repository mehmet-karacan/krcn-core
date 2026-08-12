"""Validated paths for legacy and project-capsule KRCN user homes."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Mapping

from .json_documents import pretty_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
HOME_LAYOUT_SCHEMA = "schemas/user-home-layout.schema.json"
PROJECT_CAPSULE_SCHEMA = "schemas/project-capsule-manifest.schema.json"
HOME_LAYOUT_FILE = "layout.json"
PROJECT_HOME_FILE = "project-home.json"
CURRENT_LAYOUT_VERSION = 2

PROJECT_COLLECTION_PATHS = {
    "project-capsules": "",
    "projects": "",
    "workspaces": "workspaces",
    "source-bindings": "bindings/source-bindings",
    "integrations": "bindings/integrations",
    "source-states": "derived/source-states",
    "project-integrations": "integration",
    "authoritative-sources": "knowledge/authoritative-sources",
    "knowledge": "knowledge/records",
    "information-relations": "knowledge/relations",
    "memory": "memory",
    "work-items": "work/items",
    "work-events": "work/events",
    "oracle-metadata-snapshots": "database/oracle/snapshots",
    "oracle-schema-objects": "database/oracle/objects",
    "oracle-object-revisions": "database/oracle/revisions",
    "oracle-dependencies": "database/oracle/dependencies",
    "oracle-collection-reports": "database/oracle/reports",
    "orchestration-states": "runtime/orchestration-states",
    "orchestration-events": "runtime/events/orchestration",
    "orchestration-checkpoints": "runtime/checkpoints/orchestration",
    "orchestration-handoffs": "runtime/orchestration-handoffs",
    "model-inventory": "models",
    "model-health": "derived/model-health",
}

GLOBAL_COLLECTION_PATHS = {
    key: ("project-capsules" if key == "project-capsules" else value)
    for key, value in PROJECT_COLLECTION_PATHS.items()
}


class HomeLayoutError(ValueError):
    """Raised when a KRCN home layout marker or path is unsafe."""


def _portable_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise HomeLayoutError(f"{label} must be a portable identifier")
    return value


def user_home_layout_payload() -> dict[str, object]:
    """Return the deterministic layout v2 marker payload."""

    return {
        "schema_ref": HOME_LAYOUT_SCHEMA,
        "schema_version": 1,
        "layout_version": CURRENT_LAYOUT_VERSION,
        "projects_root": "projects",
        "global_root": "global",
        "local_root": "local",
        "source_copy": False,
    }


def user_home_layout_bytes() -> bytes:
    return pretty_json_bytes(user_home_layout_payload())


def project_capsule_payload(project_id: str) -> dict[str, object]:
    """Return the portable project capsule identity and safety boundary."""

    project = _portable_identifier(project_id, "project id")
    return {
        "schema_ref": PROJECT_CAPSULE_SCHEMA,
        "schema_version": 1,
        "layout_version": CURRENT_LAYOUT_VERSION,
        "project_id": project,
        "source_content_included": False,
        "machine_locator_portable": False,
        "secret_values_included": False,
        "active_locks_portable": False,
    }


def _parse_layout(payload: object) -> int:
    expected = {
        "schema_ref",
        "schema_version",
        "layout_version",
        "projects_root",
        "global_root",
        "local_root",
        "source_copy",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise HomeLayoutError("user-home layout marker fields are invalid")
    if (
        payload.get("schema_ref") != HOME_LAYOUT_SCHEMA
        or payload.get("schema_version") != 1
        or payload.get("layout_version") != CURRENT_LAYOUT_VERSION
        or payload.get("projects_root") != "projects"
        or payload.get("global_root") != "global"
        or payload.get("local_root") != "local"
        or payload.get("source_copy") is not False
    ):
        raise HomeLayoutError("user-home layout marker is invalid")
    return CURRENT_LAYOUT_VERSION


def home_layout_version(data_root: Path) -> int:
    """Resolve layout v1 or v2 without mutating the KRCN home."""

    root = data_root.resolve(strict=False)
    marker = root / HOME_LAYOUT_FILE
    if marker.exists():
        if marker.is_symlink() or not marker.is_file():
            raise HomeLayoutError("user-home layout marker must be a regular file")
        try:
            return _parse_layout(json.loads(marker.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HomeLayoutError("user-home layout marker is unreadable") from exc
    project_marker = root / PROJECT_HOME_FILE
    if project_marker.exists():
        if project_marker.is_symlink() or not project_marker.is_file():
            raise HomeLayoutError("project-home marker must be a regular file")
        try:
            payload = json.loads(project_marker.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HomeLayoutError("project-home marker is unreadable") from exc
        if isinstance(payload, dict) and payload.get("layout_version") == 2:
            return CURRENT_LAYOUT_VERSION
    return 1


def project_capsule_root(data_root: Path, project_id: str) -> Path:
    project = _portable_identifier(project_id, "project id")
    return data_root.resolve(strict=False) / "projects" / project


def _collection_relative_path(
    record_type: str,
    record_id: str,
    project_id: str | None,
) -> PurePosixPath:
    _portable_identifier(record_id, "record id")
    mapping = PROJECT_COLLECTION_PATHS if project_id is not None else GLOBAL_COLLECTION_PATHS
    if record_type not in mapping:
        raise HomeLayoutError("record type has no layout v2 path")
    if project_id is not None:
        project = _portable_identifier(project_id, "project id")
        root = PurePosixPath("projects", project)
    else:
        root = PurePosixPath("global")
    if record_type == "project-capsules":
        return root / ("manifest.json" if project_id is not None else f"{record_id}.json")
    if record_type == "projects":
        return root / ("project.json" if project_id is not None else f"{record_id}.json")
    directory = mapping[record_type]
    return root / directory / f"{record_id}.json"


def collection_target(
    data_root: Path,
    record_type: str,
    record_id: str,
    project_id: str | None,
) -> Path:
    relative = _collection_relative_path(record_type, record_id, project_id)
    return data_root.resolve(strict=False).joinpath(*relative.parts)


def collection_target_ref(
    record_type: str,
    record_id: str,
    project_id: str | None,
) -> str:
    return f".krcn/{_collection_relative_path(record_type, record_id, project_id).as_posix()}"


def project_derived_path(data_root: Path, project_id: str, relative: str) -> Path:
    project = _portable_identifier(project_id, "project id")
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise HomeLayoutError("project derived path is not portable")
    return data_root.resolve(strict=False).joinpath(
        "projects", project, "derived", *path.parts
    )


def global_derived_path(data_root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise HomeLayoutError("global derived path is not portable")
    return data_root.resolve(strict=False).joinpath("global", "derived", *path.parts)


def validate_project_capsule_payload(
    payload: Mapping[str, object],
    project_id: str,
) -> None:
    if dict(payload) != project_capsule_payload(project_id):
        raise HomeLayoutError("project capsule manifest is invalid")

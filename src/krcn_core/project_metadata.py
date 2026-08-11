"""Safe project metadata and portable identity inference."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .local_store import LocalWorkspaceStore


MAX_MARKER_BYTES = 64 * 1024
MAX_DISPLAY_NAME = 160
MAX_PROJECT_ID = 53


class ProjectMetadataError(ValueError):
    """Raised when safe project metadata cannot be inferred."""


@dataclass(frozen=True)
class ProjectMetadata:
    project_name: str
    project_id: str
    workspace_id: str
    binding_id: str
    metadata_source: str
    collision_index: int
    inference_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-metadata-inference.schema.json",
            "schema_version": 1,
            "project_name": self.project_name,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "binding_id": self.binding_id,
            "metadata_source": self.metadata_source,
            "collision_index": self.collision_index,
            "inference_digest": self.inference_digest,
            "path_disclosed": False,
        }


def _read_marker(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > MAX_MARKER_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _toml_name(path: Path, section: str) -> str | None:
    content = _read_marker(path)
    if content is None:
        return None
    try:
        payload = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    selected = payload.get(section)
    if not isinstance(selected, dict):
        return None
    name = selected.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _package_name(path: Path) -> str | None:
    content = _read_marker(path)
    if content is None:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _display_name(source_root: Path) -> tuple[str, str]:
    candidates = (
        (_toml_name(source_root / "pyproject.toml", "project"), "pyproject"),
        (_package_name(source_root / "package.json"), "package-json"),
        (_toml_name(source_root / "Cargo.toml", "package"), "cargo"),
    )
    for name, source in candidates:
        if name:
            return name[:MAX_DISPLAY_NAME], source
    try:
        project_files = sorted(
            path
            for path in source_root.glob("*.csproj")
            if path.is_file() and not path.is_symlink()
        )
    except OSError:
        project_files = []
    if project_files:
        return project_files[0].stem[:MAX_DISPLAY_NAME], "csproj"
    fallback = source_root.name.strip()
    if not fallback:
        raise ProjectMetadataError("project directory must have a usable name")
    return fallback[:MAX_DISPLAY_NAME], "directory"


def portable_slug(value: str) -> str:
    """Convert a human project name into a stable portable identifier base."""

    folded = value.casefold().translate(str.maketrans({"ı": "i"}))
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_value = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isascii()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if not slug:
        slug = "project"
    if not slug[0].isalpha():
        slug = f"project-{slug}"
    return slug[:MAX_PROJECT_ID].rstrip("-")


def _same_local_directory(locator_value: object, source_root: Path) -> bool:
    if not isinstance(locator_value, str) or not locator_value.strip():
        return False
    try:
        candidate = Path(locator_value)
        if not candidate.is_absolute():
            return False
        return os.path.normcase(str(candidate.resolve())) == os.path.normcase(
            str(source_root)
        )
    except OSError:
        return False


def _reject_duplicate_binding(
    source_root: Path,
    store: LocalWorkspaceStore,
) -> None:
    for record in store.list_records("source-bindings"):
        locator = record.payload.get("locator")
        if (
            isinstance(locator, dict)
            and locator.get("kind") == "local-path"
            and _same_local_directory(locator.get("value"), source_root)
        ):
            raise ProjectMetadataError(
                "project directory is already registered by an existing source binding"
            )


def _candidate_id(base: str, collision_index: int) -> str:
    suffix = "" if collision_index == 1 else f"-{collision_index}"
    prefix = base[: MAX_PROJECT_ID - len(suffix)].rstrip("-")
    return f"{prefix}{suffix}"


def infer_project_metadata(
    source_root: Path,
    store: LocalWorkspaceStore,
) -> ProjectMetadata:
    """Infer names and unused portable IDs without mutating source or user data."""

    if not source_root.is_absolute() or source_root.is_symlink():
        raise ProjectMetadataError(
            "project directory must be an existing absolute regular directory"
        )
    try:
        resolved = source_root.resolve()
    except OSError as exc:
        raise ProjectMetadataError("project directory could not be resolved") from exc
    if not resolved.is_dir() or resolved == Path(resolved.anchor):
        raise ProjectMetadataError(
            "project directory must be an existing absolute regular directory"
        )
    _reject_duplicate_binding(resolved, store)
    project_name, metadata_source = _display_name(resolved)
    base = portable_slug(project_name)
    for collision_index in range(1, 10_000):
        project_id = _candidate_id(base, collision_index)
        workspace_id = f"{project_id}-workspace"
        binding_id = f"{project_id}-local"
        if all(
            store.read(record_type, record_id) is None
            for record_type, record_id in (
                ("projects", project_id),
                ("workspaces", workspace_id),
                ("source-bindings", binding_id),
            )
        ):
            digest_input = "\n".join(
                (
                    project_name,
                    project_id,
                    workspace_id,
                    binding_id,
                    metadata_source,
                    str(collision_index),
                )
            )
            return ProjectMetadata(
                project_name=project_name,
                project_id=project_id,
                workspace_id=workspace_id,
                binding_id=binding_id,
                metadata_source=metadata_source,
                collision_index=collision_index,
                inference_digest=hashlib.sha256(
                    digest_input.encode("utf-8")
                ).hexdigest(),
            )
    raise ProjectMetadataError("portable project identifiers are exhausted")

"""Read-only project and document discovery for local source bindings."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .adapter_gate import AdapterAuthorization, AdapterDescriptor, AdapterOperation
from .foundation import load_json
from .source_bindings import SourceBinding


DOCUMENT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".pdf", ".docx"}
TECHNOLOGY_MARKERS = {
    "cargo.toml": "Rust",
    "go.mod": "Go",
    "package.json": "Node.js",
    "pom.xml": "Java",
    "pyproject.toml": "Python",
}
PLSQL_SUFFIXES = {".pkb", ".pks", ".plb", ".pls", ".tpb", ".tps"}
CONFIGURATION_NAMES = {
    "cargo.toml",
    "go.mod",
    "package.json",
    "pom.xml",
    "pyproject.toml",
}


class DiscoveryError(ValueError):
    """Raised when a source cannot be inspected within the safe boundary."""


LOCAL_DISCOVERY_ADAPTER = AdapterDescriptor(
    adapter_id="local-discovery",
    version="1.0.0",
    source_kinds=("project", "document", "directory"),
    resource_type="source",
    operations=(
        AdapterOperation(
            operation_id="discover",
            required_capabilities=("read", "metadata"),
            default_effect="allow",
            mutation_effect=False,
            network_effect=False,
        ),
    ),
)


@dataclass(frozen=True)
class FileEvidence:
    relative_path: str
    kind: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    binding_id: str
    source_id: str
    binding_revision: int
    root_digest: str
    files: tuple[FileEvidence, ...]
    technologies: tuple[str, ...]
    skipped: Mapping[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "binding_id": self.binding_id,
            "source_id": self.source_id,
            "binding_revision": self.binding_revision,
            "root_digest": self.root_digest,
            "files": [item.as_dict() for item in self.files],
            "technologies": list(self.technologies),
            "skipped": dict(self.skipped),
        }


def load_discovery_policy(repo_root: Path) -> dict:
    """Load the versioned import boundary used for local discovery."""

    policy = load_json(repo_root / "config" / "import-policy.json")
    if not isinstance(policy.get("blocked_globs"), list):
        raise DiscoveryError("discovery policy blocked_globs must be a list")
    if not isinstance(policy.get("maximum_text_file_bytes"), int):
        raise DiscoveryError("discovery policy maximum size must be an integer")
    return policy


def _is_blocked(relative_path: str, patterns: list[str]) -> bool:
    candidates = {
        relative_path,
        f"{relative_path}/entry",
        f"root/{relative_path}",
        f"root/{relative_path}/entry",
    }
    return any(
        fnmatch.fnmatch(candidate, pattern)
        for candidate in candidates
        for pattern in patterns
    )


def _classify_file(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.name.lower() in CONFIGURATION_NAMES or path.suffix.lower() in {
        ".csproj",
        ".sln",
    }:
        return "configuration"
    if path.suffix.lower() in DOCUMENT_SUFFIXES:
        return "document"
    return "source"


def _technology_for(relative_path: str) -> str | None:
    path = PurePosixPath(relative_path)
    name = path.name.lower()
    if name in TECHNOLOGY_MARKERS:
        return TECHNOLOGY_MARKERS[name]
    if path.suffix.lower() in {".csproj", ".sln"}:
        return ".NET"
    if path.suffix.lower() in PLSQL_SUFFIXES:
        return "PL/SQL"
    return None


def _is_link_like(entry: os.DirEntry[str]) -> bool:
    """Reject symbolic links and Windows directory junctions."""

    if entry.is_symlink():
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_point and attributes & reparse_point)


def _stable_hash(path: Path) -> tuple[int, str] | None:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        return None
    return after.st_size, digest.hexdigest()


def discover_local_source(
    binding: SourceBinding,
    policy: dict,
    authorization: AdapterAuthorization,
    *,
    maximum_files: int = 10_000,
) -> DiscoveryResult:
    """Inspect a local source without changing it or exposing its root path."""

    request = authorization.request
    if (
        request.adapter_id != LOCAL_DISCOVERY_ADAPTER.adapter_id
        or request.operation != "discover"
        or request.binding_id != binding.binding_id
        or request.binding_revision != binding.revision
        or request.policy_effect == "deny"
        or request.mutation_effect
        or request.network_effect
    ):
        raise DiscoveryError("adapter authorization does not match discovery request")
    if binding.locator.kind != "local-path":
        raise DiscoveryError("discovery requires a local-path source binding")
    if binding.default_access != "read-only" or "write" in binding.capabilities:
        raise DiscoveryError("discovery requires a read-only source binding")
    if not {"read", "metadata"}.issubset(binding.capabilities):
        raise DiscoveryError("discovery requires read and metadata capabilities")
    root_candidate = Path(binding.locator.value)
    if not root_candidate.is_absolute():
        raise DiscoveryError("source locator must be an absolute local path")
    if root_candidate.is_symlink():
        raise DiscoveryError("source root may not be a symbolic link")
    root = root_candidate.resolve()
    if not root.is_dir():
        raise DiscoveryError("source root must be an existing directory")
    blocked_globs = policy.get("blocked_globs")
    maximum_bytes = policy.get("maximum_text_file_bytes")
    if not isinstance(blocked_globs, list) or any(
        not isinstance(item, str) for item in blocked_globs
    ):
        raise DiscoveryError("blocked path policy is invalid")
    if not isinstance(maximum_bytes, int) or maximum_bytes < 1:
        raise DiscoveryError("maximum file size policy is invalid")
    if maximum_files < 1:
        raise DiscoveryError("maximum file count must be positive")

    skipped = {
        "blocked": 0,
        "symlink": 0,
        "too_large": 0,
        "unstable": 0,
        "unreadable": 0,
    }
    files: list[FileEvidence] = []
    technologies: set[str] = set()
    scanned_files = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.lower())
        except OSError:
            skipped["unreadable"] += 1
            continue
        for entry in entries:
            entry_path = Path(entry.path)
            relative_path = entry_path.relative_to(root).as_posix()
            try:
                if _is_link_like(entry):
                    skipped["symlink"] += 1
                    continue
                if _is_blocked(relative_path, blocked_globs):
                    skipped["blocked"] += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    skipped["unreadable"] += 1
                    continue
                scanned_files += 1
                if scanned_files > maximum_files:
                    raise DiscoveryError("source exceeds the discovery file limit")
                size = entry.stat(follow_symlinks=False).st_size
                if size > maximum_bytes:
                    skipped["too_large"] += 1
                    continue
                stable = _stable_hash(entry_path)
                if stable is None:
                    skipped["unstable"] += 1
                    continue
            except OSError:
                skipped["unreadable"] += 1
                continue
            stable_size, digest = stable
            files.append(
                FileEvidence(
                    relative_path=relative_path,
                    kind=_classify_file(relative_path),
                    size=stable_size,
                    sha256=digest,
                )
            )
            technology = _technology_for(relative_path)
            if technology:
                technologies.add(technology)

    files.sort(key=lambda item: item.relative_path)
    digest_payload = [item.as_dict() for item in files]
    root_digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return DiscoveryResult(
        binding_id=binding.binding_id,
        source_id=binding.source_id,
        binding_revision=binding.revision,
        root_digest=root_digest,
        files=tuple(files),
        technologies=tuple(sorted(technologies)),
        skipped=skipped,
    )

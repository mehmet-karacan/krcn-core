"""Validated derived state produced from read-only discovery."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from .discovery import DiscoveryResult, FileEvidence


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class SourceStateError(ValueError):
    """Raised when derived source state is invalid or inconsistent."""


@dataclass(frozen=True)
class SourceState:
    binding_id: str
    binding_revision: int
    root_digest: str
    files: tuple[FileEvidence, ...]
    technologies: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "binding_id": self.binding_id,
            "binding_revision": self.binding_revision,
            "root_digest": self.root_digest,
            "files": [item.as_dict() for item in self.files],
            "technologies": list(self.technologies),
        }


def _files_digest(files: tuple[FileEvidence, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            [item.as_dict() for item in files],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source_state_from_discovery(result: DiscoveryResult) -> SourceState:
    return SourceState(
        binding_id=result.binding_id,
        binding_revision=result.binding_revision,
        root_digest=result.root_digest,
        files=result.files,
        technologies=result.technologies,
    )


def parse_source_state(payload: Mapping[str, object]) -> SourceState:
    """Parse stored derived state and verify its root digest."""

    expected_fields = {
        "schema_version",
        "binding_id",
        "binding_revision",
        "root_digest",
        "files",
        "technologies",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields:
        raise SourceStateError("source state fields are invalid")
    if payload.get("schema_version") != 1:
        raise SourceStateError("source state schema_version must be 1")
    binding_id = payload.get("binding_id")
    if not isinstance(binding_id, str) or not IDENTIFIER.fullmatch(binding_id):
        raise SourceStateError("source state binding id is invalid")
    binding_revision = payload.get("binding_revision")
    if (
        not isinstance(binding_revision, int)
        or isinstance(binding_revision, bool)
        or binding_revision < 1
    ):
        raise SourceStateError("source state binding revision is invalid")
    root_digest = payload.get("root_digest")
    if not isinstance(root_digest, str) or not SHA256.fullmatch(root_digest):
        raise SourceStateError("source state root digest is invalid")
    files_payload = payload.get("files")
    if not isinstance(files_payload, list):
        raise SourceStateError("source state files must be a list")
    files: list[FileEvidence] = []
    seen_paths: set[str] = set()
    for item in files_payload:
        if not isinstance(item, dict) or set(item) != {
            "relative_path",
            "kind",
            "size",
            "sha256",
        }:
            raise SourceStateError("source state file evidence is invalid")
        relative_path = item.get("relative_path")
        kind = item.get("kind")
        size = item.get("size")
        sha256 = item.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or relative_path.startswith("/")
            or "\\" in relative_path
            or ".." in relative_path.split("/")
            or relative_path in seen_paths
        ):
            raise SourceStateError("source state relative path is invalid")
        seen_paths.add(relative_path)
        if kind not in {"source", "document", "configuration"}:
            raise SourceStateError("source state file kind is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise SourceStateError("source state file size is invalid")
        if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
            raise SourceStateError("source state file hash is invalid")
        files.append(FileEvidence(relative_path, kind, size, sha256))
    files_tuple = tuple(sorted(files, key=lambda item: item.relative_path))
    if _files_digest(files_tuple) != root_digest:
        raise SourceStateError("source state root digest does not match files")
    technologies_payload = payload.get("technologies")
    if not isinstance(technologies_payload, list) or any(
        not isinstance(item, str) or not item for item in technologies_payload
    ):
        raise SourceStateError("source state technologies are invalid")
    technologies = tuple(technologies_payload)
    if len(set(technologies)) != len(technologies):
        raise SourceStateError("source state technologies must be unique")
    return SourceState(
        binding_id=binding_id,
        binding_revision=binding_revision,
        root_digest=root_digest,
        files=files_tuple,
        technologies=technologies,
    )

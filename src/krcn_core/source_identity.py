"""Portable identities derived from read-only external source discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .discovery import DiscoveryResult


SHA256 = re.compile(r"^[a-f0-9]{64}$")
ALGORITHM = "krcn-discovery-tree-sha256-v1"


class SourceIdentityError(ValueError):
    """Raised when an external source identity cannot be trusted."""


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str
    binding_id: str
    algorithm: str
    digest: str
    file_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "source_id": self.source_id,
            "binding_id": self.binding_id,
            "algorithm": self.algorithm,
            "digest": self.digest,
            "file_count": self.file_count,
        }


def source_identity_from_discovery(result: DiscoveryResult) -> SourceIdentity:
    """Create a path-independent identity from read-only discovery evidence."""

    if not SHA256.fullmatch(result.root_digest):
        raise SourceIdentityError("discovery root digest is invalid")
    return SourceIdentity(
        source_id=result.source_id,
        binding_id=result.binding_id,
        algorithm=ALGORITHM,
        digest=result.root_digest,
        file_count=len(result.files),
    )


def parse_source_identity(payload: object) -> SourceIdentity:
    """Parse a portable identity that contains no physical source locator."""

    expected = {
        "schema_version",
        "source_id",
        "binding_id",
        "algorithm",
        "digest",
        "file_count",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise SourceIdentityError("source identity fields are invalid")
    if payload.get("schema_version") != 1:
        raise SourceIdentityError("source identity schema_version must be 1")
    source_id = payload.get("source_id")
    binding_id = payload.get("binding_id")
    if not isinstance(source_id, str) or not source_id:
        raise SourceIdentityError("source identity source_id is invalid")
    if not isinstance(binding_id, str) or not binding_id:
        raise SourceIdentityError("source identity binding_id is invalid")
    if payload.get("algorithm") != ALGORITHM:
        raise SourceIdentityError("source identity algorithm is invalid")
    digest = payload.get("digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise SourceIdentityError("source identity digest is invalid")
    file_count = payload.get("file_count")
    if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count < 0:
        raise SourceIdentityError("source identity file_count is invalid")
    return SourceIdentity(source_id, binding_id, ALGORITHM, digest, file_count)


def identities_match(expected: SourceIdentity, candidate: SourceIdentity) -> bool:
    """Compare logical and content identity without consulting a physical path."""

    return expected == candidate


def assert_external_source(source_root: Path, user_home: Path) -> tuple[Path, Path]:
    """Prove that a source and KRCN user home are separate directory trees."""

    source = source_root.resolve(strict=False)
    home = user_home.resolve(strict=False)
    try:
        source.relative_to(home)
    except ValueError:
        pass
    else:
        raise SourceIdentityError("external source may not be inside KRCN user home")
    try:
        home.relative_to(source)
    except ValueError:
        pass
    else:
        raise SourceIdentityError("KRCN user home may not be inside external source")
    return source, home


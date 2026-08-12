"""Oracle schema metadata snapshots and project-scoped retrieval.

The module deliberately exposes named metadata transport operations instead of
accepting SQL text. Database row data is outside this boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .home_layout import project_capsule_root, project_derived_path
from .json_documents import canonical_json_bytes, pretty_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
TOKEN = re.compile(r"\w+", re.UNICODE)
SUPPORTED_OBJECT_TYPES = frozenset(
    {
        "CLUSTER",
        "CONSTRAINT",
        "DATABASE_LINK",
        "FUNCTION",
        "GRANT",
        "INDEX",
        "MATERIALIZED_VIEW",
        "MATERIALIZED_VIEW_LOG",
        "PACKAGE_BODY",
        "PACKAGE_SPEC",
        "PROCEDURE",
        "SEQUENCE",
        "SYNONYM",
        "TABLE",
        "TRIGGER",
        "TYPE_BODY",
        "TYPE_SPEC",
        "VIEW",
    }
)
COLLECTION_MODES = frozenset({"select-compatible", "batch-open"})
DEPENDENCY_KINDS = frozenset(
    {"depends-on", "references", "implements", "contains", "grants-access-to"}
)
SECRET_KEY = re.compile(
    r"(?:password|passwd|credential|secret|token|wallet|connection[_-]?string|private[_-]?key)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?i)(?:identified\s+by|password\s*=|passwd\s*=|token\s*=|://[^/\s:@]+:[^/@\s]+@)"
)
ROW_DATA_KEYS = frozenset(
    {
        "application_data",
        "record",
        "records",
        "row",
        "rows",
        "sample_rows",
        "sample_values",
        "table_data",
    }
)
VECTOR_DIMENSIONS = 192
INDEX_REVISION = 1


class OracleMetadataError(ValueError):
    """Raised when Oracle metadata crosses a safety or integrity boundary."""


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise OracleMetadataError(f"{label} must be a portable identifier")
    return value


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OracleMetadataError(f"{label} must be non-empty text")
    if "\x00" in value:
        raise OracleMetadataError(f"{label} contains a null character")
    return unicodedata.normalize("NFC", value.strip())


def _object_type(value: object) -> str:
    normalized = _non_empty(value, "object type").upper().replace(" ", "_")
    aliases = {
        "PACKAGE": "PACKAGE_SPEC",
        "PACKAGE_BODY": "PACKAGE_BODY",
        "TYPE": "TYPE_SPEC",
        "TYPE_BODY": "TYPE_BODY",
        "DB_LINK": "DATABASE_LINK",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_OBJECT_TYPES:
        raise OracleMetadataError("Oracle object type is not allowed")
    return normalized


def _secret_free(value: object) -> object:
    """Return JSON-compatible metadata while removing secret-like fields."""

    if isinstance(value, Mapping):
        cleaned: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise OracleMetadataError("structured metadata keys are invalid")
            if SECRET_KEY.search(key):
                continue
            if key.casefold() in ROW_DATA_KEYS:
                raise OracleMetadataError("database row data is prohibited")
            cleaned[key] = _secret_free(nested)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_secret_free(item) for item in value]
    if isinstance(value, str):
        if SECRET_VALUE.search(value):
            return "[REDACTED]"
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise OracleMetadataError("structured metadata contains a non-finite number")
        return value
    raise OracleMetadataError("structured metadata must be JSON-compatible")


def _sanitize_structured_metadata(
    identity: "OracleObjectIdentity",
    value: Mapping[str, object],
) -> dict[str, object]:
    cleaned = _secret_free(value)
    if not isinstance(cleaned, dict):
        raise OracleMetadataError("Oracle structured metadata must be an object")
    if identity.object_type == "DATABASE_LINK":
        allowed = {"public", "credential_present", "target_class"}
        return {key: nested for key, nested in cleaned.items() if key in allowed}
    return cleaned


@dataclass(frozen=True)
class OracleObjectIdentity:
    owner: str
    object_type: str
    name: str
    edition: str | None = None
    container: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner", _non_empty(self.owner, "owner"))
        object.__setattr__(self, "object_type", _object_type(self.object_type))
        object.__setattr__(self, "name", _non_empty(self.name, "object name"))
        if self.edition is not None:
            object.__setattr__(self, "edition", _non_empty(self.edition, "edition"))
        if self.container is not None:
            object.__setattr__(self, "container", _non_empty(self.container, "container"))

    def as_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "object_type": self.object_type,
            "name": self.name,
            "edition": self.edition,
            "container": self.container,
        }

    @property
    def object_id(self) -> str:
        return "ora-" + _canonical_digest(self.as_dict())[:40]

    @property
    def logical_group_id(self) -> str:
        identity = self.as_dict()
        if self.object_type in {"PACKAGE_SPEC", "PACKAGE_BODY"}:
            identity["object_type"] = "PACKAGE"
        if self.object_type in {"TYPE_SPEC", "TYPE_BODY"}:
            identity["object_type"] = "TYPE"
        return "ora-group-" + _canonical_digest(identity)[:40]


@dataclass(frozen=True)
class OracleInventoryEntry:
    identity: OracleObjectIdentity
    change_token: str
    status: str = "VALID"

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_token", _non_empty(self.change_token, "change token"))
        object.__setattr__(self, "status", _non_empty(self.status, "object status").upper())


@dataclass(frozen=True)
class OracleDependencyEvidence:
    target: OracleObjectIdentity
    relation_kind: str
    evidence_kind: str
    source_digest: str

    def __post_init__(self) -> None:
        if self.relation_kind not in DEPENDENCY_KINDS:
            raise OracleMetadataError("Oracle dependency relation is invalid")
        if self.evidence_kind not in {"dictionary", "plscope", "structural"}:
            raise OracleMetadataError("Oracle dependency evidence is invalid")
        if not SHA256.fullmatch(self.source_digest):
            raise OracleMetadataError("Oracle dependency digest is invalid")


class OracleMetadataTransport(Protocol):
    """A named-operation transport. It must not expose arbitrary SQL execution."""

    def inventory(
        self,
        owners: tuple[str, ...],
        object_types: tuple[str, ...],
    ) -> Sequence[OracleInventoryEntry]: ...

    def fetch_ddl_select(self, identity: OracleObjectIdentity) -> str: ...

    def fetch_ddl_batch(self, identity: OracleObjectIdentity) -> str: ...

    def fetch_structured_metadata(self, identity: OracleObjectIdentity) -> Mapping[str, object]: ...

    def fetch_dependencies(self, identity: OracleObjectIdentity) -> Sequence[OracleDependencyEvidence]: ...


@dataclass(frozen=True)
class OracleCollectionPolicy:
    owners: tuple[str, ...]
    object_types: tuple[str, ...]
    mode: str = "select-compatible"

    def __post_init__(self) -> None:
        owners = tuple(sorted({_non_empty(item, "allowed owner") for item in self.owners}))
        types = tuple(sorted({_object_type(item) for item in self.object_types}))
        if not owners or not types:
            raise OracleMetadataError("Oracle owner and object type allowlists are required")
        if self.mode not in COLLECTION_MODES:
            raise OracleMetadataError("Oracle collection mode is invalid")
        object.__setattr__(self, "owners", owners)
        object.__setattr__(self, "object_types", types)


@dataclass(frozen=True)
class OracleReadAuthorization:
    binding_id: str
    binding_revision: int
    operation: str
    approved: bool

    def __post_init__(self) -> None:
        _identifier(self.binding_id, "binding id")
        if not isinstance(self.binding_revision, int) or self.binding_revision < 1:
            raise OracleMetadataError("binding revision must be positive")
        if self.operation not in {"metadata-select", "metadata-batch-open"}:
            raise OracleMetadataError("Oracle metadata authorization operation is invalid")


@dataclass(frozen=True)
class OracleCollectedObject:
    inventory: OracleInventoryEntry
    normalized_ddl: str
    structured_metadata: Mapping[str, object]
    dependencies: tuple[OracleDependencyEvidence, ...]
    reused: bool = False

    @property
    def content_digest(self) -> str:
        return _canonical_digest(
            {
                "identity": self.inventory.identity.as_dict(),
                "ddl": self.normalized_ddl,
                "structured_metadata": dict(self.structured_metadata),
            }
        )

    @property
    def revision_id(self) -> str:
        return "orv-" + self.content_digest[:40]


@dataclass(frozen=True)
class OracleSnapshot:
    project_id: str
    integration_id: str
    binding_id: str
    binding_revision: int
    mode: str
    complete: bool
    objects: tuple[OracleCollectedObject, ...]
    reused_object_count: int = 0

    @property
    def snapshot_id(self) -> str:
        identity = {
            "project_id": self.project_id,
            "integration_id": self.integration_id,
            "binding_id": self.binding_id,
            "binding_revision": self.binding_revision,
            "mode": self.mode,
            "complete": self.complete,
            "objects": [
                {
                    "object_id": item.inventory.identity.object_id,
                    "change_token": item.inventory.change_token,
                    "revision_id": item.revision_id,
                }
                for item in self.objects
            ],
        }
        return "ors-" + _canonical_digest(identity)[:40]


def _normalize_ddl(identity: OracleObjectIdentity, ddl: str) -> str:
    value = _non_empty(ddl, "Oracle DDL")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.split("\n")).strip()
    if identity.object_type == "DATABASE_LINK":
        return (
            f'CREATE DATABASE LINK "{identity.owner}"."{identity.name}" '
            "/* connection details redacted */"
        )
    if SECRET_VALUE.search(value):
        raise OracleMetadataError("secret-like text is prohibited in Oracle metadata")
    return value


def collect_oracle_snapshot(
    project_id: str,
    integration_id: str,
    transport: OracleMetadataTransport,
    policy: OracleCollectionPolicy,
    authorization: OracleReadAuthorization,
    *,
    complete: bool,
    data_root: Path | None = None,
) -> OracleSnapshot:
    """Collect schema metadata through named, authorized transport methods."""

    project = _identifier(project_id, "project id")
    integration = _identifier(integration_id, "integration id")
    if not authorization.approved:
        raise OracleMetadataError("Oracle metadata read requires explicit authorization")
    expected_operation = (
        "metadata-select" if policy.mode == "select-compatible" else "metadata-batch-open"
    )
    if authorization.operation != expected_operation:
        raise OracleMetadataError("Oracle metadata authorization does not match collection mode")
    inventory = tuple(transport.inventory(policy.owners, policy.object_types))
    seen: set[str] = set()
    collected: list[OracleCollectedObject] = []
    reused = 0
    for item in inventory:
        if not isinstance(item, OracleInventoryEntry):
            raise OracleMetadataError("Oracle inventory entry is invalid")
        identity = item.identity
        if identity.owner not in policy.owners or identity.object_type not in policy.object_types:
            raise OracleMetadataError("Oracle transport returned an object outside the allowlist")
        if identity.object_id in seen:
            raise OracleMetadataError("Oracle inventory contains duplicate object identities")
        seen.add(identity.object_id)
        previous = (
            _load_reusable_object(data_root, project, item)
            if data_root is not None
            else None
        )
        if previous is not None:
            collected.append(previous)
            reused += 1
            continue
        ddl = (
            transport.fetch_ddl_select(identity)
            if policy.mode == "select-compatible"
            else transport.fetch_ddl_batch(identity)
        )
        structured = _sanitize_structured_metadata(
            identity,
            transport.fetch_structured_metadata(identity),
        )
        dependencies = tuple(transport.fetch_dependencies(identity))
        collected.append(
            OracleCollectedObject(
                item,
                _normalize_ddl(identity, ddl),
                structured,
                dependencies,
            )
        )
    return OracleSnapshot(
        project,
        integration,
        authorization.binding_id,
        authorization.binding_revision,
        policy.mode,
        bool(complete),
        tuple(sorted(collected, key=lambda item: item.inventory.identity.object_id)),
        reused,
    )


@dataclass(frozen=True)
class OracleWriteEffect:
    target: Path
    target_ref: str
    expected_before: str | None
    content: bytes

    @property
    def content_digest(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class OracleApplyPlan:
    project_id: str
    snapshot_id: str
    effects: tuple[OracleWriteEffect, ...]
    new_revision_count: int
    unchanged_object_count: int
    retired_object_count: int

    @property
    def plan_id(self) -> str:
        return _canonical_digest(
            {
                "project_id": self.project_id,
                "snapshot_id": self.snapshot_id,
                "effects": [
                    {
                        "target_ref": effect.target_ref,
                        "expected_before": effect.expected_before,
                        "content_digest": effect.content_digest,
                    }
                    for effect in self.effects
                ],
            }
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/oracle-metadata-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "snapshot_id": self.snapshot_id,
            "write_count": len(self.effects),
            "new_revision_count": self.new_revision_count,
            "unchanged_object_count": self.unchanged_object_count,
            "retired_object_count": self.retired_object_count,
            "row_data_collected": False,
            "source_sql_accepted": False,
            "effects": [
                {
                    "operation": (
                        "update" if effect.expected_before is not None else "create"
                    ),
                    "target_ref": effect.target_ref,
                    "expected_before": effect.expected_before,
                    "content_digest": effect.content_digest,
                }
                for effect in self.effects
            ],
        }


@dataclass(frozen=True)
class OracleApplyAuthorization:
    plan_id: str
    approval_id: str
    approved: bool


def _file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise OracleMetadataError("Oracle metadata target must be a regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OracleMetadataError("stored Oracle metadata is unreadable") from exc
    if not isinstance(payload, dict):
        raise OracleMetadataError("stored Oracle metadata must be an object")
    return payload


def _load_reusable_object(
    data_root: Path,
    project_id: str,
    inventory: OracleInventoryEntry,
) -> OracleCollectedObject | None:
    """Reuse an unchanged authoritative revision without another DDL fetch."""

    root = _oracle_root(data_root, project_id)
    object_path = root / "objects" / f"{inventory.identity.object_id}.json"
    if not object_path.exists():
        return None
    object_payload = _read_json(object_path)
    if (
        object_payload.get("lifecycle") != "current"
        or object_payload.get("change_token") != inventory.change_token
        or object_payload.get("identity") != inventory.identity.as_dict()
    ):
        return None
    revision_id = object_payload.get("current_revision_id")
    if not isinstance(revision_id, str):
        raise OracleMetadataError("stored Oracle object revision is invalid")
    revision_payload = _read_json(root / "revisions" / f"{revision_id}.json")
    if (
        revision_payload.get("object_id") != inventory.identity.object_id
        or revision_payload.get("identity") != inventory.identity.as_dict()
        or revision_payload.get("revision_id") != revision_id
    ):
        raise OracleMetadataError("stored Oracle object revision identity is invalid")
    ddl = revision_payload.get("normalized_ddl")
    structured = revision_payload.get("structured_metadata")
    if not isinstance(ddl, str) or not isinstance(structured, dict):
        raise OracleMetadataError("stored Oracle object revision content is invalid")
    candidate = OracleCollectedObject(inventory, ddl, structured, (), True)
    if (
        candidate.revision_id != revision_id
        or candidate.content_digest != revision_payload.get("content_digest")
    ):
        raise OracleMetadataError("stored Oracle object revision digest is invalid")
    return candidate


def _oracle_root(data_root: Path, project_id: str) -> Path:
    return project_capsule_root(data_root, project_id) / "database" / "oracle"


def _relative_ref(project_id: str, *parts: str) -> str:
    return ".krcn/projects/" + project_id + "/database/oracle/" + "/".join(parts)


def _effect(path: Path, target_ref: str, payload: Mapping[str, object]) -> OracleWriteEffect:
    return OracleWriteEffect(path, target_ref, _file_digest(path), pretty_json_bytes(payload))


def _revision_payload(snapshot: OracleSnapshot, item: OracleCollectedObject) -> dict[str, object]:
    identity = item.inventory.identity
    return {
        "schema_version": 1,
        "revision_id": item.revision_id,
        "object_id": identity.object_id,
        "project_id": snapshot.project_id,
        "snapshot_id": snapshot.snapshot_id,
        "identity": identity.as_dict(),
        "logical_group_id": identity.logical_group_id,
        "change_token": item.inventory.change_token,
        "status": item.inventory.status,
        "normalized_ddl": item.normalized_ddl,
        "structured_metadata": dict(item.structured_metadata),
        "content_digest": item.content_digest,
    }


def _object_payload(
    snapshot: OracleSnapshot,
    item: OracleCollectedObject,
    *,
    lifecycle: str = "current",
) -> dict[str, object]:
    identity = item.inventory.identity
    return {
        "schema_version": 1,
        "object_id": identity.object_id,
        "project_id": snapshot.project_id,
        "integration_id": snapshot.integration_id,
        "identity": identity.as_dict(),
        "logical_group_id": identity.logical_group_id,
        "current_revision_id": item.revision_id,
        "change_token": item.inventory.change_token,
        "status": item.inventory.status,
        "lifecycle": lifecycle,
        "last_seen_snapshot_id": snapshot.snapshot_id,
    }


def _dependency_payload(
    snapshot: OracleSnapshot,
    item: OracleCollectedObject,
    dependency: OracleDependencyEvidence,
) -> dict[str, object]:
    from_id = item.inventory.identity.object_id
    to_id = dependency.target.object_id
    identity = {
        "from_object_id": from_id,
        "to_object_id": to_id,
        "relation_kind": dependency.relation_kind,
        "evidence_kind": dependency.evidence_kind,
        "source_digest": dependency.source_digest,
    }
    dependency_id = "ord-" + _canonical_digest(identity)[:40]
    return {
        "schema_version": 1,
        "dependency_id": dependency_id,
        "project_id": snapshot.project_id,
        **identity,
        "from_revision_id": item.revision_id,
        "snapshot_id": snapshot.snapshot_id,
        "lifecycle": "current",
    }


def prepare_oracle_apply(data_root: Path, snapshot: OracleSnapshot) -> OracleApplyPlan:
    """Build an exact user-data plan without modifying authoritative files."""

    root = _oracle_root(data_root, snapshot.project_id)
    object_dir = root / "objects"
    effects: list[OracleWriteEffect] = []
    unchanged = 0
    new_revisions = 0
    seen_ids: set[str] = set()
    for item in snapshot.objects:
        object_id = item.inventory.identity.object_id
        seen_ids.add(object_id)
        revision_path = root / "revisions" / f"{item.revision_id}.json"
        revision_payload = _revision_payload(snapshot, item)
        if not revision_path.exists():
            effects.append(
                _effect(
                    revision_path,
                    _relative_ref(snapshot.project_id, "revisions", revision_path.name),
                    revision_payload,
                )
            )
            new_revisions += 1
        else:
            existing_revision = _read_json(revision_path)
            if existing_revision.get("content_digest") != item.content_digest:
                raise OracleMetadataError("Oracle revision identity collision")
        object_path = object_dir / f"{object_id}.json"
        object_payload = _object_payload(snapshot, item)
        if object_path.exists() and _read_json(object_path) == object_payload:
            unchanged += 1
        else:
            effects.append(
                _effect(
                    object_path,
                    _relative_ref(snapshot.project_id, "objects", object_path.name),
                    object_payload,
                )
            )
        current_dependency_ids: set[str] = set()
        for dependency in item.dependencies:
            payload = _dependency_payload(snapshot, item, dependency)
            current_dependency_ids.add(str(payload["dependency_id"]))
            path = root / "dependencies" / f"{payload['dependency_id']}.json"
            if not path.exists() or _read_json(path) != payload:
                effects.append(
                    _effect(
                        path,
                        _relative_ref(snapshot.project_id, "dependencies", path.name),
                        payload,
                    )
                )
        dependency_dir = root / "dependencies"
        if not item.reused and dependency_dir.exists():
            for path in sorted(dependency_dir.glob("*.json")):
                payload = _read_json(path)
                if (
                    payload.get("from_object_id") == object_id
                    and payload.get("dependency_id") not in current_dependency_ids
                    and payload.get("lifecycle") != "retired"
                ):
                    retired_payload = dict(payload)
                    retired_payload["lifecycle"] = "retired"
                    retired_payload["snapshot_id"] = snapshot.snapshot_id
                    effects.append(
                        _effect(
                            path,
                            _relative_ref(snapshot.project_id, "dependencies", path.name),
                            retired_payload,
                        )
                    )

    retired = 0
    if snapshot.complete and object_dir.exists():
        for path in sorted(object_dir.glob("*.json")):
            payload = _read_json(path)
            object_id = payload.get("object_id")
            if isinstance(object_id, str) and object_id not in seen_ids and payload.get("lifecycle") != "retired":
                retired_payload = dict(payload)
                retired_payload["lifecycle"] = "retired"
                retired_payload["last_seen_snapshot_id"] = snapshot.snapshot_id
                effects.append(
                    _effect(
                        path,
                        _relative_ref(snapshot.project_id, "objects", path.name),
                        retired_payload,
                    )
                )
                retired += 1

    snapshot_payload = {
        "schema_version": 1,
        "snapshot_id": snapshot.snapshot_id,
        "project_id": snapshot.project_id,
        "integration_id": snapshot.integration_id,
        "binding_id": snapshot.binding_id,
        "binding_revision": snapshot.binding_revision,
        "collection_mode": snapshot.mode,
        "complete": snapshot.complete,
        "object_ids": sorted(seen_ids),
        "catalog_digest": _canonical_digest(
            [
                [item.inventory.identity.object_id, item.revision_id]
                for item in snapshot.objects
            ]
        ),
        "row_data_collected": False,
    }
    snapshot_path = root / "snapshots" / f"{snapshot.snapshot_id}.json"
    if not snapshot_path.exists():
        effects.append(
            _effect(
                snapshot_path,
                _relative_ref(snapshot.project_id, "snapshots", snapshot_path.name),
                snapshot_payload,
            )
        )
    effects.sort(key=lambda item: item.target_ref)
    return OracleApplyPlan(
        snapshot.project_id,
        snapshot.snapshot_id,
        tuple(effects),
        new_revisions,
        unchanged,
        retired,
    )


def apply_oracle_plan(
    plan: OracleApplyPlan,
    authorization: OracleApplyAuthorization,
) -> dict[str, object]:
    """Apply an exact Oracle metadata plan with stale-plan protection."""

    if (
        not authorization.approved
        or authorization.plan_id != plan.plan_id
        or not authorization.approval_id.strip()
    ):
        raise OracleMetadataError("matching Oracle metadata apply approval is required")
    for effect in plan.effects:
        if _file_digest(effect.target) != effect.expected_before:
            raise OracleMetadataError("Oracle metadata plan is stale")
    originals: dict[Path, bytes | None] = {}
    for effect in plan.effects:
        effect.target.parent.mkdir(parents=True, exist_ok=True)
        if effect.target.parent.is_symlink() or effect.target.is_symlink():
            raise OracleMetadataError("Oracle metadata path may not use symbolic links")
        originals[effect.target] = (
            effect.target.read_bytes() if effect.target.exists() else None
        )

    def replace_bytes(target: Path, content: bytes) -> None:
        handle, name = tempfile.mkstemp(
            dir=target.parent,
            prefix=".oracle-",
            suffix=".json",
        )
        temporary = Path(name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    applied: list[Path] = []
    try:
        for effect in plan.effects:
            replace_bytes(effect.target, effect.content)
            applied.append(effect.target)
    except Exception:
        for target in reversed(applied):
            original = originals[target]
            if original is None:
                target.unlink(missing_ok=True)
            else:
                replace_bytes(target, original)
        raise
    return {
        **plan.public_summary(),
        "status": "applied",
        "integrity_verified": all(
            _file_digest(effect.target) == effect.content_digest for effect in plan.effects
        ),
    }


@dataclass(frozen=True)
class OracleChunk:
    chunk_id: str
    object_id: str
    revision_id: str
    section_kind: str
    symbol_path: str
    text: str
    content_digest: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class OracleIndexPlan:
    project_id: str
    catalog_digest: str
    chunks: tuple[OracleChunk, ...]
    dependencies: tuple[Mapping[str, object], ...]
    processed_chunk_count: int
    reused_chunk_count: int
    removed_chunk_count: int
    expected_before: str | None

    @property
    def index_digest(self) -> str:
        return _canonical_digest(
            {
                "project_id": self.project_id,
                "catalog_digest": self.catalog_digest,
                "chunks": [
                    [item.chunk_id, item.content_digest, list(item.vector)] for item in self.chunks
                ],
                "dependencies": [dict(item) for item in self.dependencies],
            }
        )

    @property
    def plan_id(self) -> str:
        return _canonical_digest(
            {
                "index_digest": self.index_digest,
                "expected_before": self.expected_before,
                "target_ref": f".krcn/projects/{self.project_id}/derived/retrieval/oracle-metadata-v1.sqlite",
            }
        )


@dataclass(frozen=True)
class OracleIndexAuthorization:
    plan_id: str
    approved: bool = True


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(TOKEN.findall(unicodedata.normalize("NFKC", value).casefold()))


def _vector(value: str) -> tuple[float, ...]:
    values = [0.0] * VECTOR_DIMENSIONS
    for token in _tokens(value):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in values))
    if norm:
        values = [item / norm for item in values]
    return tuple(float(f"{item:.12f}") for item in values)


def _sections(revision: Mapping[str, object]) -> tuple[tuple[str, str, str], ...]:
    identity = revision["identity"]
    if not isinstance(identity, dict):
        raise OracleMetadataError("Oracle revision identity is invalid")
    object_type = str(identity["object_type"])
    name = str(identity["name"])
    ddl = str(revision["normalized_ddl"])
    structured = revision.get("structured_metadata", {})
    sections: list[tuple[str, str, str]] = [("ddl", name, ddl)]
    if isinstance(structured, dict):
        for key in ("columns", "constraints", "indexes", "grants", "members"):
            value = structured.get(key)
            if isinstance(value, list) and value:
                for index, item in enumerate(value):
                    sections.append(
                        (key.rstrip("s"), f"{name}/{key}/{index + 1}", json.dumps(item, ensure_ascii=False, sort_keys=True))
                    )
    if object_type in {"PACKAGE_SPEC", "PACKAGE_BODY", "TYPE_SPEC", "TYPE_BODY", "PROCEDURE", "FUNCTION"}:
        lines = ddl.splitlines()
        if len(lines) > 80:
            sections = []
            for start in range(0, len(lines), 70):
                part = "\n".join(lines[start : start + 80])
                sections.append(("program-unit", f"{name}/lines/{start + 1}", part))
    return tuple(sections)


def oracle_index_path(data_root: Path, project_id: str) -> Path:
    return project_derived_path(data_root, project_id, "retrieval/oracle-metadata-v1.sqlite")


def _existing_vectors(path: Path) -> tuple[dict[str, tuple[str, tuple[float, ...]]], set[str]]:
    if not path.exists():
        return {}, set()
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT chunk_id, content_digest, vector_json FROM chunks").fetchall()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise OracleMetadataError("existing Oracle metadata index is invalid") from exc
    if integrity != "ok":
        raise OracleMetadataError("existing Oracle metadata index integrity failed")
    vectors: dict[str, tuple[str, tuple[float, ...]]] = {}
    for chunk_id, digest, vector_json in rows:
        try:
            vector = tuple(float(item) for item in json.loads(vector_json))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OracleMetadataError("existing Oracle vector is invalid") from exc
        if len(vector) != VECTOR_DIMENSIONS:
            raise OracleMetadataError("existing Oracle vector dimensions are invalid")
        vectors[str(chunk_id)] = (str(digest), vector)
    return vectors, set(vectors)


def prepare_oracle_index(data_root: Path, project_id: str) -> OracleIndexPlan:
    """Plan an incremental project-scoped Oracle retrieval index."""

    project = _identifier(project_id, "project id")
    root = _oracle_root(data_root, project)
    object_dir = root / "objects"
    revisions: list[dict[str, object]] = []
    if object_dir.exists():
        for object_path in sorted(object_dir.glob("*.json")):
            object_payload = _read_json(object_path)
            if object_payload.get("lifecycle") != "current":
                continue
            revision_id = object_payload.get("current_revision_id")
            if not isinstance(revision_id, str):
                raise OracleMetadataError("Oracle object revision reference is invalid")
            revisions.append(_read_json(root / "revisions" / f"{revision_id}.json"))
    path = oracle_index_path(data_root, project)
    existing, previous_ids = _existing_vectors(path)
    chunks: list[OracleChunk] = []
    processed = 0
    reused = 0
    for revision in revisions:
        object_id = str(revision["object_id"])
        revision_id = str(revision["revision_id"])
        identity = revision["identity"]
        if not isinstance(identity, dict):
            raise OracleMetadataError("Oracle revision identity is invalid")
        prefix = " ".join(
            str(identity.get(key) or "") for key in ("owner", "object_type", "name", "edition")
        )
        for section_kind, symbol_path, text in _sections(revision):
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunk_id = "orc-" + _canonical_digest(
                [object_id, revision_id, section_kind, symbol_path, digest]
            )[:40]
            current = existing.get(chunk_id)
            if current is not None and current[0] == digest:
                vector = current[1]
                reused += 1
            else:
                vector = _vector(" ".join((prefix, symbol_path, text)))
                processed += 1
            chunks.append(
                OracleChunk(chunk_id, object_id, revision_id, section_kind, symbol_path, text, digest, vector)
            )
    chunks.sort(key=lambda item: item.chunk_id)
    dependencies = tuple(
        payload
        for path in sorted((root / "dependencies").glob("*.json"))
        for payload in (_read_json(path),)
        if payload.get("lifecycle") == "current"
    ) if (root / "dependencies").exists() else ()
    catalog_digest = _canonical_digest(
        [[item["object_id"], item["revision_id"], item["content_digest"]] for item in revisions]
    )
    return OracleIndexPlan(
        project,
        catalog_digest,
        tuple(chunks),
        dependencies,
        processed,
        reused,
        len(previous_ids - {item.chunk_id for item in chunks}),
        _file_digest(path),
    )


def apply_oracle_index(
    data_root: Path,
    plan: OracleIndexPlan,
    authorization: OracleIndexAuthorization,
) -> dict[str, object]:
    """Atomically build the exact derived Oracle SQLite index."""

    if not authorization.approved or authorization.plan_id != plan.plan_id:
        raise OracleMetadataError("matching Oracle index authorization is required")
    target = oracle_index_path(data_root, plan.project_id)
    if _file_digest(target) != plan.expected_before:
        raise OracleMetadataError("Oracle index plan is stale")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=".oracle-index-", suffix=".sqlite")
    os.close(handle)
    temporary = Path(name)
    temporary.unlink()
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("CREATE TABLE objects (object_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL)")
            connection.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, object_id TEXT NOT NULL, revision_id TEXT NOT NULL, section_kind TEXT NOT NULL, symbol_path TEXT NOT NULL, text TEXT NOT NULL, content_digest TEXT NOT NULL, vector_json TEXT NOT NULL)")
            connection.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text, symbol_path)")
            connection.execute("CREATE TABLE dependencies (dependency_id TEXT PRIMARY KEY, from_object_id TEXT NOT NULL, to_object_id TEXT NOT NULL, relation_kind TEXT NOT NULL, evidence_kind TEXT NOT NULL, source_digest TEXT NOT NULL)")
            metadata = {
                "index_revision": str(INDEX_REVISION),
                "project_id": plan.project_id,
                "catalog_digest": plan.catalog_digest,
                "index_digest": plan.index_digest,
                "vector_dimensions": str(VECTOR_DIMENSIONS),
                "embedding_profile_id": "deterministic-hashing",
                "row_data_collected": "false",
            }
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", sorted(metadata.items()))
            objects = sorted({(item.object_id, item.revision_id) for item in plan.chunks})
            connection.executemany("INSERT INTO objects VALUES (?, ?)", objects)
            for item in plan.chunks:
                connection.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (item.chunk_id, item.object_id, item.revision_id, item.section_kind, item.symbol_path, item.text, item.content_digest, json.dumps(item.vector, separators=(",", ":"))),
                )
                connection.execute("INSERT INTO chunks_fts VALUES (?, ?, ?)", (item.chunk_id, item.text, item.symbol_path))
            for item in plan.dependencies:
                connection.execute(
                    "INSERT INTO dependencies VALUES (?, ?, ?, ?, ?, ?)",
                    tuple(str(item[key]) for key in ("dependency_id", "from_object_id", "to_object_id", "relation_kind", "evidence_kind", "source_digest")),
                )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        if integrity != "ok":
            raise OracleMetadataError("Oracle metadata index verification failed")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "project_id": plan.project_id,
        "index_digest": plan.index_digest,
        "chunk_count": len(plan.chunks),
        "processed_chunk_count": plan.processed_chunk_count,
        "reused_chunk_count": plan.reused_chunk_count,
        "removed_chunk_count": plan.removed_chunk_count,
        "integrity_verified": True,
        "row_data_collected": False,
    }


def search_oracle_metadata(
    data_root: Path,
    project_id: str,
    text: str,
    *,
    owner: str | None = None,
    object_type: str | None = None,
    limit: int = 10,
) -> dict[str, object]:
    """Search exact, FTS, and deterministic vectors in one project index."""

    project = _identifier(project_id, "project id")
    query = _non_empty(text, "Oracle metadata query")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise OracleMetadataError("Oracle metadata search limit is invalid")
    type_filter = _object_type(object_type) if object_type is not None else None
    root = _oracle_root(data_root, project)
    identities: dict[str, dict[str, object]] = {}
    for path in sorted((root / "objects").glob("*.json")):
        payload = _read_json(path)
        if payload.get("lifecycle") == "current" and isinstance(payload.get("identity"), dict):
            identities[str(payload["object_id"])] = dict(payload["identity"])
    target = oracle_index_path(data_root, project)
    if not target.exists():
        raise OracleMetadataError("Oracle metadata index is unavailable")
    connection = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute("SELECT chunk_id, object_id, revision_id, section_kind, symbol_path, text, content_digest, vector_json FROM chunks").fetchall()
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    finally:
        connection.close()
    query_tokens = set(_tokens(query))
    query_vector = _vector(query)
    hits: list[dict[str, object]] = []
    for row in rows:
        identity = identities.get(str(row[1]))
        if identity is None:
            continue
        if owner is not None and str(identity.get("owner")) != owner:
            continue
        if type_filter is not None and str(identity.get("object_type")) != type_filter:
            continue
        candidate = " ".join((str(identity.get("owner")), str(identity.get("object_type")), str(identity.get("name")), str(row[4]), str(row[5])))
        candidate_tokens = set(_tokens(candidate))
        exact = 1.0 if query.casefold() in candidate.casefold() else 0.0
        fts = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))
        vector = tuple(float(item) for item in json.loads(row[7]))
        semantic = max(0.0, sum(left * right for left, right in zip(query_vector, vector)))
        score = 0.4 * exact + 0.25 * fts + 0.35 * semantic
        if score <= 0:
            continue
        hits.append(
            {
                "chunk_id": str(row[0]),
                "object_id": str(row[1]),
                "revision_id": str(row[2]),
                "identity": identity,
                "section_kind": str(row[3]),
                "symbol_path": str(row[4]),
                "content_digest": str(row[6]),
                "score": float(f"{score:.6f}"),
                "text": str(row[5]),
            }
        )
    hits.sort(key=lambda item: (-float(item["score"]), str(item["object_id"]), str(item["chunk_id"])))
    return {
        "project_id": project,
        "query_digest": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "index_digest": metadata.get("index_digest"),
        "hit_count": min(len(hits), limit),
        "hits": hits[:limit],
        "remote": False,
        "row_data_collected": False,
    }


def retrieve_oracle_dependencies(
    data_root: Path,
    project_id: str,
    object_id: str,
    *,
    direction: str = "outbound",
    max_depth: int = 3,
) -> dict[str, object]:
    """Traverse exact provenance-bearing Oracle dependency edges."""

    project = _identifier(project_id, "project id")
    if not isinstance(object_id, str) or not object_id.startswith("ora-"):
        raise OracleMetadataError("Oracle object id is invalid")
    if direction not in {"outbound", "inbound", "both"}:
        raise OracleMetadataError("Oracle dependency direction is invalid")
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 0 <= max_depth <= 10:
        raise OracleMetadataError("Oracle dependency depth is invalid")
    connection = sqlite3.connect(oracle_index_path(data_root, project).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT dependency_id, from_object_id, to_object_id, relation_kind, evidence_kind, source_digest FROM dependencies").fetchall()
    finally:
        connection.close()
    edges = [
        {
            "dependency_id": str(row[0]),
            "from_object_id": str(row[1]),
            "to_object_id": str(row[2]),
            "relation_kind": str(row[3]),
            "evidence_kind": str(row[4]),
            "source_digest": str(row[5]),
        }
        for row in rows
    ]
    visited = {object_id}
    frontier = {object_id}
    selected: dict[str, dict[str, object]] = {}
    for _ in range(max_depth):
        next_frontier: set[str] = set()
        for edge in edges:
            outbound = direction in {"outbound", "both"} and edge["from_object_id"] in frontier
            inbound = direction in {"inbound", "both"} and edge["to_object_id"] in frontier
            if not outbound and not inbound:
                continue
            selected[str(edge["dependency_id"])] = edge
            target = str(edge["to_object_id"] if outbound else edge["from_object_id"])
            if target not in visited:
                visited.add(target)
                next_frontier.add(target)
        frontier = next_frontier
        if not frontier:
            break
    return {
        "project_id": project,
        "seed_object_id": object_id,
        "direction": direction,
        "node_ids": sorted(visited),
        "edges": [selected[key] for key in sorted(selected)],
        "provenance_preserved": True,
    }

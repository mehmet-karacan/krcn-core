"""Revision-aware capability registry with explicit, authority-neutral selection."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .foundation import load_json
from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
CAPABILITY = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
KINDS = {"adapter", "agent", "model", "secret-provider", "skill", "tool"}
ROLES = {"planner", "worker", "verifier"}
SIDE_EFFECTS = {"read", "write", "execute", "network"}
OWNERSHIP_CLASSES = {"core", "runtime", "user-data", "derived", "secrets", "unmanaged"}
PROVIDER_MODES = {"none", "local", "remote"}
APPROVAL_TRIGGERS = {
    "scope-change",
    "user-data-mutation",
    "remote-provider-use",
    "irreversible-effect",
    "policy-change",
    "capability-escalation",
}
STATUSES = {"active", "disabled"}


class CapabilityRegistryError(ValueError):
    """Raised when registry declarations or explicit selections are unsafe."""


@dataclass(frozen=True)
class CapabilityRecord:
    record_id: str
    kind: str
    role: str | None
    revision: int
    capabilities: tuple[str, ...]
    side_effects: tuple[str, ...]
    read_ownership: tuple[str, ...]
    write_ownership: tuple[str, ...]
    provider_mode: str
    approval_triggers: tuple[str, ...]
    status: str
    record_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "kind": self.kind,
            "role": self.role,
            "revision": self.revision,
            "capabilities": list(self.capabilities),
            "side_effects": list(self.side_effects),
            "read_ownership": list(self.read_ownership),
            "write_ownership": list(self.write_ownership),
            "provider_mode": self.provider_mode,
            "approval_triggers": list(self.approval_triggers),
            "status": self.status,
            "record_digest": self.record_digest,
        }


@dataclass(frozen=True)
class CapabilityRegistry:
    revision: int
    records: tuple[CapabilityRecord, ...]

    @property
    def registry_digest(self) -> str:
        identity = {
            "revision": self.revision,
            "records": [record.as_dict() for record in self.records],
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def get(self, record_id: str) -> CapabilityRecord | None:
        return next((item for item in self.records if item.record_id == record_id), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/capability-registry.schema.json",
            "schema_version": 1,
            "revision": self.revision,
            "registry_digest": self.registry_digest,
            "records": [record.as_dict() for record in self.records],
        }


@dataclass(frozen=True)
class CapabilitySelection:
    selected: tuple[CapabilityRecord, ...]
    required_capabilities: tuple[str, ...]
    approval_triggers: tuple[str, ...]
    registry_digest: str

    @property
    def selection_digest(self) -> str:
        identity = {
            "record_refs": [
                {
                    "record_id": item.record_id,
                    "revision": item.revision,
                    "record_digest": item.record_digest,
                }
                for item in self.selected
            ],
            "required_capabilities": list(self.required_capabilities),
            "approval_triggers": list(self.approval_triggers),
            "registry_digest": self.registry_digest,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "record_refs": [
                {
                    "record_id": item.record_id,
                    "kind": item.kind,
                    "revision": item.revision,
                    "record_digest": item.record_digest,
                }
                for item in self.selected
            ],
            "required_capabilities": list(self.required_capabilities),
            "approval_triggers": list(self.approval_triggers),
            "registry_digest": self.registry_digest,
            "selection_digest": self.selection_digest,
            "grants_authority": False,
        }


def _string_list(value: object, allowed: set[str] | re.Pattern[str], label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise CapabilityRegistryError(f"{label} must be a unique list")
    if isinstance(allowed, set):
        valid = all(item in allowed for item in value)
    else:
        valid = all(allowed.fullmatch(item) for item in value)
    if not valid:
        raise CapabilityRegistryError(f"{label} contains invalid values")
    return tuple(sorted(value))


def capability_record_digest(payload: dict[str, object]) -> str:
    identity = dict(payload)
    identity.pop("record_digest", None)
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def parse_capability_record(payload: object) -> CapabilityRecord:
    expected = {
        "record_id",
        "kind",
        "role",
        "revision",
        "capabilities",
        "side_effects",
        "read_ownership",
        "write_ownership",
        "provider_mode",
        "approval_triggers",
        "status",
        "record_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise CapabilityRegistryError("capability record fields are invalid")
    record_id = payload.get("record_id")
    if not isinstance(record_id, str) or not IDENTIFIER.fullmatch(record_id):
        raise CapabilityRegistryError("capability record_id is invalid")
    kind = payload.get("kind")
    if kind not in KINDS:
        raise CapabilityRegistryError("capability kind is invalid")
    role = payload.get("role")
    if kind == "agent":
        if role not in ROLES:
            raise CapabilityRegistryError("agent capability role is invalid")
    elif role is not None:
        raise CapabilityRegistryError("only agent records may declare a role")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CapabilityRegistryError("capability revision is invalid")
    capabilities = _string_list(payload.get("capabilities"), CAPABILITY, "capabilities")
    if not capabilities:
        raise CapabilityRegistryError("capabilities must not be empty")
    side_effects = _string_list(payload.get("side_effects"), SIDE_EFFECTS, "side_effects")
    read_ownership = _string_list(
        payload.get("read_ownership"), OWNERSHIP_CLASSES, "read_ownership"
    )
    write_ownership = _string_list(
        payload.get("write_ownership"), OWNERSHIP_CLASSES, "write_ownership"
    )
    provider_mode = payload.get("provider_mode")
    if provider_mode not in PROVIDER_MODES:
        raise CapabilityRegistryError("provider_mode is invalid")
    approval_triggers = _string_list(
        payload.get("approval_triggers"),
        APPROVAL_TRIGGERS,
        "approval_triggers",
    )
    status = payload.get("status")
    if status not in STATUSES:
        raise CapabilityRegistryError("capability status is invalid")
    if write_ownership and "write" not in side_effects:
        raise CapabilityRegistryError("write ownership requires a write side effect")
    if "write" in side_effects and kind == "agent" and role != "worker":
        raise CapabilityRegistryError("only worker agents may declare write effects")
    if "user-data" in write_ownership and "user-data-mutation" not in approval_triggers:
        raise CapabilityRegistryError("user-data writes require an approval trigger")
    if provider_mode == "remote":
        if "network" not in side_effects or "remote-provider-use" not in approval_triggers:
            raise CapabilityRegistryError("remote capability requires network approval")
    elif "network" in side_effects:
        raise CapabilityRegistryError("network effects require remote provider mode")
    digest = payload.get("record_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise CapabilityRegistryError("capability record_digest is invalid")
    if digest != capability_record_digest(payload):
        raise CapabilityRegistryError("capability record_digest does not match")
    return CapabilityRecord(
        str(record_id),
        str(kind),
        role if isinstance(role, str) else None,
        revision,
        capabilities,
        side_effects,
        read_ownership,
        write_ownership,
        str(provider_mode),
        approval_triggers,
        str(status),
        digest,
    )


def build_capability_registry(payload: object) -> CapabilityRegistry:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_ref",
        "schema_version",
        "revision",
        "records",
    }:
        raise CapabilityRegistryError("capability registry fields are invalid")
    if payload.get("schema_ref") != "schemas/capability-registry.schema.json":
        raise CapabilityRegistryError("capability registry schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise CapabilityRegistryError("capability registry schema_version must be 1")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CapabilityRegistryError("capability registry revision is invalid")
    records_payload = payload.get("records")
    if not isinstance(records_payload, list):
        raise CapabilityRegistryError("capability records must be a list")
    records = tuple(parse_capability_record(item) for item in records_payload)
    if len({item.record_id for item in records}) != len(records):
        raise CapabilityRegistryError("capability record ids must be unique")
    if {item.kind for item in records if item.status == "active"} != KINDS:
        raise CapabilityRegistryError("active registry must cover every capability kind")
    return CapabilityRegistry(
        revision,
        tuple(sorted(records, key=lambda item: (item.kind, item.record_id))),
    )


def load_capability_registry(repo_root: Path) -> CapabilityRegistry:
    return build_capability_registry(load_json(repo_root / "config" / "capability-registry.json"))


def select_capability_records(
    registry: CapabilityRegistry,
    record_refs: Iterable[str],
    required_capabilities: Iterable[str],
) -> CapabilitySelection:
    refs = tuple(record_refs)
    if not refs or len(set(refs)) != len(refs):
        raise CapabilityRegistryError("capability record refs must be explicit and unique")
    required = tuple(sorted(set(required_capabilities)))
    if not required or any(not CAPABILITY.fullmatch(item) for item in required):
        raise CapabilityRegistryError("required capabilities are invalid")
    selected = []
    for record_id in refs:
        if not isinstance(record_id, str) or not IDENTIFIER.fullmatch(record_id):
            raise CapabilityRegistryError("capability record ref is invalid")
        record = registry.get(record_id)
        if record is None:
            raise CapabilityRegistryError("explicit capability record was not found")
        if record.status != "active":
            raise CapabilityRegistryError("explicit capability record is not active")
        selected.append(record)
    available = {item for record in selected for item in record.capabilities}
    missing = set(required) - available
    if missing:
        raise CapabilityRegistryError(
            "selected records do not provide: " + ", ".join(sorted(missing))
        )
    ordered = tuple(sorted(selected, key=lambda item: (item.kind, item.record_id)))
    return CapabilitySelection(
        ordered,
        required,
        tuple(sorted({item for record in ordered for item in record.approval_triggers})),
        registry.registry_digest,
    )

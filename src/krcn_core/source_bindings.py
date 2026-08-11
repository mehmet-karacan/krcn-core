"""Portable source identities with local-only physical locators."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SOURCE_KINDS = {"project", "document", "directory", "database", "integration"}
LOCATOR_KINDS = {"local-path", "connection-ref", "uri"}
ACCESS_MODES = {"read-only", "read-write"}
CAPABILITIES = {"read", "write", "metadata", "search", "index", "execute"}


class SourceBindingError(ValueError):
    """Raised when a source binding violates the portable contract."""


@dataclass(frozen=True)
class SourceLocator:
    kind: str
    value: str


@dataclass(frozen=True)
class SourceBinding:
    schema_version: int
    binding_id: str
    source_id: str
    source_kind: str
    locator: SourceLocator
    default_access: str
    capabilities: tuple[str, ...]
    policy_refs: tuple[str, ...]
    revision: int

    def public_summary(self) -> dict[str, object]:
        """Return binding metadata without exposing a physical locator value."""

        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "locator_kind": self.locator.kind,
            "default_access": self.default_access,
            "capabilities": list(self.capabilities),
            "policy_refs": list(self.policy_refs),
            "revision": self.revision,
        }


def _identifier(value: object, field: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        errors.append(f"{field} must be a portable identifier")
        return ""
    return value


def parse_source_binding(payload: object) -> SourceBinding:
    """Validate and parse a user-owned source binding document."""

    if not isinstance(payload, dict):
        raise SourceBindingError("source binding must be an object")
    errors: list[str] = []
    expected_fields = {
        "schema_version",
        "binding_id",
        "source_id",
        "source_kind",
        "locator",
        "default_access",
        "capabilities",
        "policy_refs",
        "revision",
    }
    extra = set(payload) - expected_fields
    if extra:
        errors.append("unexpected fields: " + ", ".join(sorted(extra)))
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    binding_id = _identifier(payload.get("binding_id"), "binding_id", errors)
    source_id = _identifier(payload.get("source_id"), "source_id", errors)
    source_kind = payload.get("source_kind")
    if source_kind not in SOURCE_KINDS:
        errors.append("source_kind is invalid")

    locator_payload = payload.get("locator")
    locator = SourceLocator("", "")
    if not isinstance(locator_payload, dict) or set(locator_payload) != {"kind", "value"}:
        errors.append("locator must contain only kind and value")
    else:
        locator_kind = locator_payload.get("kind")
        locator_value = locator_payload.get("value")
        if locator_kind not in LOCATOR_KINDS:
            errors.append("locator kind is invalid")
        if not isinstance(locator_value, str) or not locator_value.strip():
            errors.append("locator value must be a non-empty string")
        locator = SourceLocator(str(locator_kind), str(locator_value))

    default_access = payload.get("default_access")
    if default_access not in ACCESS_MODES:
        errors.append("default_access is invalid")
    capabilities_payload = payload.get("capabilities")
    if not isinstance(capabilities_payload, list) or any(
        item not in CAPABILITIES for item in capabilities_payload
    ):
        errors.append("capabilities are invalid")
        capabilities: tuple[str, ...] = ()
    else:
        capabilities = tuple(dict.fromkeys(capabilities_payload))
        if len(capabilities) != len(capabilities_payload):
            errors.append("capabilities must be unique")
    if default_access == "read-only" and "write" in capabilities:
        errors.append("read-only binding cannot declare write capability")

    policy_payload = payload.get("policy_refs")
    if not isinstance(policy_payload, list):
        errors.append("policy_refs must be a list")
        policy_refs: tuple[str, ...] = ()
    else:
        policy_refs = tuple(
            _identifier(item, "policy_ref", errors) for item in policy_payload
        )
        if len(set(policy_refs)) != len(policy_refs):
            errors.append("policy_refs must be unique")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append("revision must be a positive integer")

    if errors:
        raise SourceBindingError("; ".join(errors))
    return SourceBinding(
        schema_version=1,
        binding_id=binding_id,
        source_id=source_id,
        source_kind=str(source_kind),
        locator=locator,
        default_access=str(default_access),
        capabilities=capabilities,
        policy_refs=policy_refs,
        revision=int(revision),
    )


def load_source_binding(path: Path) -> SourceBinding:
    """Read a binding from local user data without logging its locator."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceBindingError("source binding file was not found") from exc
    except json.JSONDecodeError as exc:
        raise SourceBindingError(f"source binding JSON is invalid: {exc}") from exc
    return parse_source_binding(payload)

"""Secret-safe local integration metadata validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SECRET_REFERENCE = re.compile(
    r"^(?:secret|keyring|env)://[A-Za-z0-9][A-Za-z0-9._/-]*$"
)
SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|token|api[-_]?key|secret|credential|private[-_]?key)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*="),
    re.compile(r"://[^/\s:@]+:[^/@\s]+@"),
)


class IntegrationMetadataError(ValueError):
    """Raised when integration metadata contains an invalid or secret value."""


@dataclass(frozen=True)
class IntegrationMetadata:
    integration_id: str
    adapter_id: str
    source_binding_ref: str
    status: str
    configuration: Mapping[str, object]
    secret_refs: Mapping[str, str]
    policy_refs: tuple[str, ...]
    revision: int

    def public_summary(self) -> dict[str, object]:
        """Expose metadata shape without configuration or secret reference values."""

        return {
            "integration_id": self.integration_id,
            "adapter_id": self.adapter_id,
            "source_binding_ref": self.source_binding_ref,
            "status": self.status,
            "configuration_keys": sorted(self.configuration),
            "secret_ref_names": sorted(self.secret_refs),
            "policy_refs": list(self.policy_refs),
            "revision": self.revision,
        }


def _portable_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise IntegrationMetadataError(f"{label} must be a portable identifier")
    return value


def _scan_configuration(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise IntegrationMetadataError("configuration keys must be non-empty strings")
            if SENSITIVE_KEY.search(key):
                raise IntegrationMetadataError(
                    "secret-like configuration keys must use secret_refs"
                )
            _scan_configuration(nested, (*path, key))
        return
    if isinstance(value, list):
        for nested in value:
            _scan_configuration(nested, path)
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS
    ):
        raise IntegrationMetadataError(
            "secret-like configuration values must use secret_refs"
        )
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise IntegrationMetadataError("configuration values must be JSON-compatible")


def _validate_secret_reference(value: object) -> str:
    if not isinstance(value, str) or not SECRET_REFERENCE.fullmatch(value):
        raise IntegrationMetadataError("secret reference is invalid")
    reference_path = value.split("://", 1)[1]
    if ".." in reference_path.split("/") or "\\" in reference_path:
        raise IntegrationMetadataError("secret reference must be portable")
    return value


def parse_integration_metadata(payload: object) -> IntegrationMetadata:
    """Validate integration metadata while rejecting literal credentials."""

    if not isinstance(payload, dict):
        raise IntegrationMetadataError("integration metadata must be an object")
    expected_fields = {
        "schema_version",
        "integration_id",
        "adapter_id",
        "source_binding_ref",
        "status",
        "configuration",
        "secret_refs",
        "policy_refs",
        "revision",
    }
    if set(payload) != expected_fields:
        raise IntegrationMetadataError("integration metadata fields are invalid")
    if payload.get("schema_version") != 1:
        raise IntegrationMetadataError("integration schema_version must be 1")
    integration_id = _portable_identifier(payload.get("integration_id"), "integration_id")
    adapter_id = _portable_identifier(payload.get("adapter_id"), "adapter_id")
    source_binding_ref = _portable_identifier(
        payload.get("source_binding_ref"), "source_binding_ref"
    )
    status = payload.get("status")
    if status not in {"active", "disabled"}:
        raise IntegrationMetadataError("integration status is invalid")
    configuration = payload.get("configuration")
    if not isinstance(configuration, dict):
        raise IntegrationMetadataError("integration configuration must be an object")
    _scan_configuration(configuration)
    secret_refs_payload = payload.get("secret_refs")
    if not isinstance(secret_refs_payload, dict):
        raise IntegrationMetadataError("secret_refs must be an object")
    secret_refs: dict[str, str] = {}
    for name, value in secret_refs_payload.items():
        secret_name = _portable_identifier(name, "secret reference name")
        secret_refs[secret_name] = _validate_secret_reference(value)
    policy_refs_payload = payload.get("policy_refs")
    if not isinstance(policy_refs_payload, list):
        raise IntegrationMetadataError("policy_refs must be a list")
    policy_refs = tuple(
        _portable_identifier(value, "policy reference") for value in policy_refs_payload
    )
    if len(set(policy_refs)) != len(policy_refs):
        raise IntegrationMetadataError("policy_refs must be unique")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise IntegrationMetadataError("integration revision must be positive")
    return IntegrationMetadata(
        integration_id=integration_id,
        adapter_id=adapter_id,
        source_binding_ref=source_binding_ref,
        status=status,
        configuration=dict(configuration),
        secret_refs=secret_refs,
        policy_refs=policy_refs,
        revision=revision,
    )

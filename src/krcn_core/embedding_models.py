"""Explicit embedding model selection and local integration contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .foundation import load_json
from .integrations import IntegrationMetadata


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
RETRIEVAL_MODES = {"dense", "sparse", "multi-vector"}


class EmbeddingModelError(ValueError):
    """Raised when an embedding model or integration contract is invalid."""


@dataclass(frozen=True)
class EmbeddingModelProfile:
    profile_id: str
    provider_id: str
    model_id: str
    name: str
    role: str
    priority: int
    vector_dimensions: int
    minimum_vector_dimensions: int
    max_input_tokens: int
    multilingual: bool
    instruction_aware: bool
    adjustable_dimensions: bool
    retrieval_modes: tuple[str, ...]
    status: str

    def public_summary(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "name": self.name,
            "role": self.role,
            "priority": self.priority,
            "vector_dimensions": self.vector_dimensions,
            "minimum_vector_dimensions": self.minimum_vector_dimensions,
            "max_input_tokens": self.max_input_tokens,
            "multilingual": self.multilingual,
            "instruction_aware": self.instruction_aware,
            "adjustable_dimensions": self.adjustable_dimensions,
            "retrieval_modes": list(self.retrieval_modes),
            "status": self.status,
        }


@dataclass(frozen=True)
class EmbeddingModelCatalog:
    selection_id: str
    default_profile_id: str
    fallback_profile_ids: tuple[str, ...]
    offline_fallback_id: str
    profiles: tuple[EmbeddingModelProfile, ...]

    def profile(self, profile_id: str) -> EmbeddingModelProfile:
        selected = next(
            (item for item in self.profiles if item.profile_id == profile_id),
            None,
        )
        if selected is None:
            raise EmbeddingModelError("embedding profile was not found")
        return selected

    @property
    def remote_order(self) -> tuple[EmbeddingModelProfile, ...]:
        return (
            self.profile(self.default_profile_id),
            *(self.profile(item) for item in self.fallback_profile_ids),
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/embedding-model-catalog.schema.json",
            "schema_version": 1,
            "selection_id": self.selection_id,
            "default_profile_id": self.default_profile_id,
            "fallback_profile_ids": list(self.fallback_profile_ids),
            "offline_fallback_id": self.offline_fallback_id,
            "profiles": [item.public_summary() for item in self.profiles],
        }


@dataclass(frozen=True)
class EmbeddingIntegrationProfile:
    integration_id: str
    endpoint: str
    model_profile_ids: tuple[str, ...]
    offline_fallback_id: str
    credential_provider: str
    credential_reference: str
    retention_assumptions: str

    def public_summary(self) -> dict[str, object]:
        return {
            "integration_id": self.integration_id,
            "endpoint_disclosed": bool(self.endpoint),
            "model_profile_ids": list(self.model_profile_ids),
            "offline_fallback_id": self.offline_fallback_id,
            "credential_provider": self.credential_provider,
            "credential_reference_disclosed": False,
            "retention_assumptions": self.retention_assumptions,
        }


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise EmbeddingModelError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str, *, maximum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EmbeddingModelError(f"{label} must be positive")
    if maximum is not None and value > maximum:
        raise EmbeddingModelError(f"{label} exceeds the supported maximum")
    return value


def _parse_model(payload: object) -> EmbeddingModelProfile:
    expected = {
        "profile_id",
        "provider_id",
        "model_id",
        "name",
        "role",
        "priority",
        "vector_dimensions",
        "minimum_vector_dimensions",
        "max_input_tokens",
        "multilingual",
        "instruction_aware",
        "adjustable_dimensions",
        "retrieval_modes",
        "status",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise EmbeddingModelError("embedding model fields are invalid")
    profile_id = _identifier(payload.get("profile_id"), "profile_id")
    provider_id = _identifier(payload.get("provider_id"), "provider_id")
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id):
        raise EmbeddingModelError("embedding model_id is invalid")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise EmbeddingModelError("embedding model name is invalid")
    role = payload.get("role")
    if role not in {"primary", "fallback"}:
        raise EmbeddingModelError("embedding model role is invalid")
    priority = _positive_integer(payload.get("priority"), "priority")
    dimensions = _positive_integer(
        payload.get("vector_dimensions"),
        "vector_dimensions",
        maximum=16_384,
    )
    minimum_dimensions = _positive_integer(
        payload.get("minimum_vector_dimensions"),
        "minimum_vector_dimensions",
        maximum=dimensions,
    )
    max_input_tokens = _positive_integer(
        payload.get("max_input_tokens"),
        "max_input_tokens",
    )
    boolean_fields = (
        "multilingual",
        "instruction_aware",
        "adjustable_dimensions",
    )
    if any(not isinstance(payload.get(field), bool) for field in boolean_fields):
        raise EmbeddingModelError("embedding model boolean fields are invalid")
    modes = payload.get("retrieval_modes")
    if (
        not isinstance(modes, list)
        or not modes
        or any(not isinstance(item, str) or item not in RETRIEVAL_MODES for item in modes)
        or len(set(modes)) != len(modes)
    ):
        raise EmbeddingModelError("embedding retrieval modes are invalid")
    if "dense" not in modes:
        raise EmbeddingModelError("embedding profile must support dense retrieval")
    status = payload.get("status")
    if status not in {"active", "disabled"}:
        raise EmbeddingModelError("embedding model status is invalid")
    if bool(payload["adjustable_dimensions"]) is False and minimum_dimensions != dimensions:
        raise EmbeddingModelError("fixed embedding dimensions must match")
    return EmbeddingModelProfile(
        profile_id,
        provider_id,
        model_id,
        name.strip(),
        str(role),
        priority,
        dimensions,
        minimum_dimensions,
        max_input_tokens,
        bool(payload["multilingual"]),
        bool(payload["instruction_aware"]),
        bool(payload["adjustable_dimensions"]),
        tuple(modes),
        str(status),
    )


def parse_embedding_model_catalog(payload: object) -> EmbeddingModelCatalog:
    expected = {
        "schema_ref",
        "schema_version",
        "selection_id",
        "default_profile_id",
        "fallback_profile_ids",
        "offline_fallback_id",
        "profiles",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise EmbeddingModelError("embedding model catalog fields are invalid")
    if payload.get("schema_ref") != "schemas/embedding-model-catalog.schema.json":
        raise EmbeddingModelError("embedding model catalog schema_ref is invalid")
    if payload.get("schema_version") != 1:
        raise EmbeddingModelError("embedding model catalog schema_version must be 1")
    selection_id = _identifier(payload.get("selection_id"), "selection_id")
    default_profile_id = _identifier(
        payload.get("default_profile_id"),
        "default_profile_id",
    )
    fallback_payload = payload.get("fallback_profile_ids")
    if (
        not isinstance(fallback_payload, list)
        or not fallback_payload
        or any(not isinstance(item, str) for item in fallback_payload)
        or len(set(fallback_payload)) != len(fallback_payload)
    ):
        raise EmbeddingModelError("embedding fallback profiles are invalid")
    fallback_ids = tuple(
        _identifier(item, "fallback profile id") for item in fallback_payload
    )
    offline_fallback_id = payload.get("offline_fallback_id")
    if offline_fallback_id != "deterministic-hashing":
        raise EmbeddingModelError("offline embedding fallback is invalid")
    profiles_payload = payload.get("profiles")
    if not isinstance(profiles_payload, list):
        raise EmbeddingModelError("embedding profiles must be a list")
    profiles = tuple(_parse_model(item) for item in profiles_payload)
    if len({item.profile_id for item in profiles}) != len(profiles):
        raise EmbeddingModelError("embedding profile ids must be unique")
    if len({item.provider_id for item in profiles}) != len(profiles):
        raise EmbeddingModelError("embedding provider ids must be unique")
    if len({item.priority for item in profiles}) != len(profiles):
        raise EmbeddingModelError("embedding priorities must be unique")
    by_id = {item.profile_id: item for item in profiles}
    if default_profile_id not in by_id or any(item not in by_id for item in fallback_ids):
        raise EmbeddingModelError("embedding selection references are invalid")
    if by_id[default_profile_id].role != "primary":
        raise EmbeddingModelError("default embedding profile must be primary")
    if any(by_id[item].role != "fallback" for item in fallback_ids):
        raise EmbeddingModelError("fallback embedding profile role is invalid")
    ordered_ids = (default_profile_id, *fallback_ids)
    ordered_priorities = tuple(by_id[item].priority for item in ordered_ids)
    if ordered_priorities != tuple(sorted(ordered_priorities)):
        raise EmbeddingModelError("embedding fallback priority is invalid")
    if any(by_id[item].status != "active" for item in ordered_ids):
        raise EmbeddingModelError("selected embedding profiles must be active")
    return EmbeddingModelCatalog(
        selection_id,
        default_profile_id,
        fallback_ids,
        str(offline_fallback_id),
        tuple(sorted(profiles, key=lambda item: item.priority)),
    )


def load_embedding_model_catalog(repo_root: Path) -> EmbeddingModelCatalog:
    return parse_embedding_model_catalog(
        load_json(repo_root / "config" / "embedding-models.json")
    )


def parse_embedding_integration(
    metadata: IntegrationMetadata,
    catalog: EmbeddingModelCatalog,
) -> EmbeddingIntegrationProfile:
    if metadata.adapter_id != "openai-compatible-embedding":
        raise EmbeddingModelError("embedding integration adapter is invalid")
    expected = {
        "endpoint",
        "model_profile_ids",
        "offline_fallback_id",
        "retention_assumptions",
    }
    configuration = dict(metadata.configuration)
    if set(configuration) != expected:
        raise EmbeddingModelError("embedding integration configuration is invalid")
    endpoint = configuration.get("endpoint")
    if not isinstance(endpoint, str):
        raise EmbeddingModelError("embedding endpoint is invalid")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise EmbeddingModelError("embedding endpoint must be a credential-free HTTPS URL")
    profile_ids_payload = configuration.get("model_profile_ids")
    if (
        not isinstance(profile_ids_payload, list)
        or any(not isinstance(item, str) for item in profile_ids_payload)
        or len(set(profile_ids_payload)) != len(profile_ids_payload)
    ):
        raise EmbeddingModelError("embedding model profile selection is invalid")
    profile_ids = tuple(
        _identifier(item, "embedding model profile id")
        for item in profile_ids_payload
    )
    expected_order = tuple(item.profile_id for item in catalog.remote_order)
    if profile_ids != expected_order:
        raise EmbeddingModelError("embedding model order must match the reviewed catalog")
    if configuration.get("offline_fallback_id") != catalog.offline_fallback_id:
        raise EmbeddingModelError("embedding offline fallback does not match the catalog")
    retention = configuration.get("retention_assumptions")
    if not isinstance(retention, str) or not retention.strip():
        raise EmbeddingModelError("embedding retention assumptions are required")
    if set(metadata.secret_refs) != {"api-key"}:
        raise EmbeddingModelError("embedding integration requires one API key reference")
    credential_reference = metadata.secret_refs["api-key"]
    if not credential_reference.startswith("opencode://"):
        raise EmbeddingModelError("embedding credential must use the OpenCode provider")
    return EmbeddingIntegrationProfile(
        metadata.integration_id,
        endpoint.rstrip("/"),
        profile_ids,
        catalog.offline_fallback_id,
        "opencode",
        credential_reference,
        retention.strip(),
    )

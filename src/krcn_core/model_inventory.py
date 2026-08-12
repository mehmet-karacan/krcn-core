"""Credential-free global model inventory with exact-plan persistence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .information_records import canonical_json
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .mutation_gate import MutationAuthorization, OwnershipResolver
from .foundation import detect_content_findings


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
MODALITIES = {"audio", "embedding", "text", "vision"}
WORKLOADS = {
    "analysis",
    "audio-transcription",
    "architecture",
    "code-review",
    "database-analysis",
    "discovery",
    "embedding",
    "general",
    "implementation",
    "performance-analysis",
    "planning",
    "reranking",
    "security-review",
    "verification",
    "vision-analysis",
}


class ModelInventoryError(ValueError):
    """Raised when model inventory data is incomplete or unsafe."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ModelInventoryError(f"{label} is invalid")
    return value


def _string_list(
    value: object,
    label: str,
    *,
    allowed: set[str] | None = None,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ModelInventoryError(f"{label} must be a unique non-empty list")
    normalized = tuple(sorted(value))
    if allowed is not None and any(item not in allowed for item in normalized):
        raise ModelInventoryError(f"{label} contains an unsupported value")
    return normalized


def build_model_inventory_record(
    entry: object,
    *,
    revision: int,
) -> dict[str, object]:
    """Normalize one user-declared model without accepting secrets or endpoints."""

    expected = {
        "model_ref",
        "provider_ref",
        "model_id",
        "display_name",
        "modalities",
        "supported_workloads",
        "client_refs",
        "remote",
        "enabled",
    }
    if not isinstance(entry, dict) or set(entry) != expected:
        raise ModelInventoryError("model inventory entry fields are invalid")
    model_ref = _identifier(entry.get("model_ref"), "model_ref")
    provider_ref = _identifier(entry.get("provider_ref"), "provider_ref")
    model_id = entry.get("model_id")
    display_name = entry.get("display_name")
    remote = entry.get("remote")
    enabled = entry.get("enabled")
    if (
        not isinstance(model_id, str)
        or len(model_id) > 300
        or not MODEL_ID.fullmatch(model_id)
        or not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name) > 200
        or not isinstance(remote, bool)
        or not isinstance(enabled, bool)
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
    ):
        raise ModelInventoryError("model inventory entry values are invalid")
    screened = json.dumps(
        {
            "model_id": model_id,
            "display_name": display_name,
            "provider_ref": provider_ref,
        },
        ensure_ascii=False,
    )
    if "://" in model_id or detect_content_findings(
        screened,
        "model-inventory.json",
        {
            "aws-access-key",
            "credential-uri",
            "generic-secret-assignment",
            "github-token",
            "private-key",
        },
    ):
        raise ModelInventoryError("model inventory contains sensitive or endpoint data")
    modalities = _string_list(entry.get("modalities"), "modalities", allowed=MODALITIES)
    workloads = _string_list(
        entry.get("supported_workloads"),
        "supported_workloads",
        allowed=WORKLOADS,
    )
    clients = _string_list(entry.get("client_refs"), "client_refs")
    for client in clients:
        _identifier(client, "client_ref")
    if "embedding" in modalities and "embedding" not in workloads:
        raise ModelInventoryError("embedding model must declare embedding workload")
    if "audio" in modalities and "audio-transcription" not in workloads:
        raise ModelInventoryError("audio model must declare transcription workload")
    if "vision" in modalities and "vision-analysis" not in workloads:
        raise ModelInventoryError("vision model must declare vision workload")
    if "text" not in modalities:
        allowed_non_text = set()
        if "embedding" in modalities:
            allowed_non_text.update({"embedding", "reranking"})
        if "audio" in modalities:
            allowed_non_text.add("audio-transcription")
        if "vision" in modalities:
            allowed_non_text.add("vision-analysis")
        if any(workload not in allowed_non_text for workload in workloads):
            raise ModelInventoryError("non-text model declares a text workload")
    semantic = {
        "model_ref": model_ref,
        "provider_ref": provider_ref,
        "model_id": model_id,
        "display_name": display_name.strip(),
        "modalities": list(modalities),
        "supported_workloads": list(workloads),
        "client_refs": list(clients),
        "remote": remote,
        "enabled": enabled,
        "credential_handling": "client-managed" if remote else "none",
    }
    return {
        "schema_ref": "schemas/model-inventory-record.schema.json",
        "schema_version": 1,
        **semantic,
        "revision": revision,
        "inventory_digest": _digest(semantic),
        "invariants": {
            "credential_values_included": False,
            "endpoint_included": False,
            "grants_authority": False,
        },
    }


def parse_model_inventory_record(payload: object) -> dict[str, object]:
    """Validate one persisted model inventory record and its semantic digest."""

    expected = {
        "schema_ref",
        "schema_version",
        "model_ref",
        "provider_ref",
        "model_id",
        "display_name",
        "modalities",
        "supported_workloads",
        "client_refs",
        "remote",
        "enabled",
        "credential_handling",
        "revision",
        "inventory_digest",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelInventoryError("model inventory record fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-inventory-record.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise ModelInventoryError("model inventory record schema is invalid")
    entry = {
        key: payload[key]
        for key in (
            "model_ref",
            "provider_ref",
            "model_id",
            "display_name",
            "modalities",
            "supported_workloads",
            "client_refs",
            "remote",
            "enabled",
        )
    }
    rebuilt = build_model_inventory_record(entry, revision=payload.get("revision"))
    if rebuilt != payload:
        raise ModelInventoryError("model inventory record is inconsistent")
    return rebuilt


@dataclass(frozen=True)
class ModelInventoryPlan:
    plan_id: str
    records: tuple[Mapping[str, object], ...]
    effect_plans: tuple[RecordWritePlan, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "model_count": len(self.records),
            "model_refs": [str(item["model_ref"]) for item in self.records],
            "enabled_count": sum(bool(item["enabled"]) for item in self.records),
            "remote_count": sum(bool(item["remote"]) for item in self.records),
            "effects": [item.public_summary() for item in self.effect_plans],
            "credential_values_included": False,
            "endpoints_included": False,
            "grants_authority": False,
        }


def prepare_model_inventory(
    store: LocalWorkspaceStore,
    ownership: OwnershipResolver,
    entries: Sequence[object],
) -> ModelInventoryPlan:
    """Prepare deterministic upserts for a complete declared inventory batch."""

    if not entries:
        raise ModelInventoryError("model inventory batch must not be empty")
    input_refs = [
        item.get("model_ref") if isinstance(item, dict) else None for item in entries
    ]
    if any(not isinstance(item, str) for item in input_refs) or len(set(input_refs)) != len(input_refs):
        raise ModelInventoryError("model inventory refs must be unique")
    records: list[dict[str, object]] = []
    effects: list[RecordWritePlan] = []
    for entry in sorted(entries, key=lambda item: str(item["model_ref"])):
        model_ref = _identifier(entry.get("model_ref"), "model_ref")
        current = store.read("model-inventory", model_ref)
        revision = 1 if current is None else current.revision + 1
        record = build_model_inventory_record(entry, revision=revision)
        if current is not None:
            parsed = parse_model_inventory_record(current.payload)
            if parsed["inventory_digest"] == record["inventory_digest"]:
                records.append(parsed)
                continue
        effects.append(
            store.prepare_put(
                "model-inventory",
                model_ref,
                record,
                expected_revision=0 if current is None else current.revision,
            )
        )
        records.append(record)
    identity = {
        "records": [
            {
                "model_ref": item["model_ref"],
                "revision": item["revision"],
                "inventory_digest": item["inventory_digest"],
            }
            for item in records
        ],
        "effect_plan_ids": [item.mutation.plan_id for item in effects],
    }
    return ModelInventoryPlan(
        _digest(identity),
        tuple(records),
        tuple(effects),
    )


def apply_model_inventory(
    store: LocalWorkspaceStore,
    plan: ModelInventoryPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> tuple[dict[str, object], ...]:
    """Apply only the exact approved model inventory effect plans."""

    expected = {item.mutation.plan_id for item in plan.effect_plans}
    if set(authorizations) != expected:
        raise ModelInventoryError("model inventory authorizations are not exact")
    applied = []
    for effect in plan.effect_plans:
        stored = store.apply_put(effect, authorizations[effect.mutation.plan_id])
        applied.append(stored.public_summary())
    return tuple(applied)


def list_model_inventory(store: LocalWorkspaceStore) -> tuple[dict[str, object], ...]:
    """Return credential-free public summaries of registered models."""

    records = []
    for stored in store.list_records("model-inventory"):
        record = parse_model_inventory_record(stored.payload)
        records.append(
            {
                "model_ref": record["model_ref"],
                "provider_ref": record["provider_ref"],
                "model_id": record["model_id"],
                "display_name": record["display_name"],
                "modalities": record["modalities"],
                "supported_workloads": record["supported_workloads"],
                "client_refs": record["client_refs"],
                "remote": record["remote"],
                "enabled": record["enabled"],
                "revision": record["revision"],
                "inventory_digest": record["inventory_digest"],
                "credential_values_included": False,
                "endpoint_included": False,
            }
        )
    return tuple(sorted(records, key=lambda item: str(item["model_ref"])))

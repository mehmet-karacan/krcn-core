"""Provider-gated synthetic model health checks and quarantine lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .foundation import load_json
from .information_records import canonical_json
from .local_store import LocalWorkspaceStore
from .model_inventory import parse_model_inventory_record
from .mutation_gate import DryRunEvidence, authorize_mutation
from .provider_gate import ProviderAuthorization, ProviderRequest, create_provider_request
from .secret_provider import SecretLease, SecretProviderError


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
FAILURE_CATEGORIES = {
    "authentication",
    "mismatch",
    "parse",
    "protocol",
    "provider-error",
    "timeout",
    "unavailable",
}


class ModelHealthError(ValueError):
    """Raised when a model probe or health record is unsafe or inconsistent."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ModelHealthError("model health time must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ModelHealthError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ModelHealthError(f"{label} is invalid") from exc
    return _utc(parsed)


@dataclass(frozen=True)
class ModelHealthPolicy:
    policy_revision: int
    probe_suite_id: str
    probe_suite_revision: int
    prompt_id: str
    expected_response: str
    timeout_seconds: int
    maximum_latency_ms: int
    quarantine_failure_threshold: int
    cooldown_seconds: int
    failure_categories: tuple[str, ...]
    policy_digest: str


def load_model_health_policy(repo_root: Path) -> ModelHealthPolicy:
    payload = load_json(repo_root / "config" / "model-health-policy.json")
    expected = {
        "schema_ref",
        "schema_version",
        "policy_revision",
        "probe_suite_id",
        "probe_suite_revision",
        "prompt_id",
        "expected_response",
        "timeout_seconds",
        "maximum_latency_ms",
        "quarantine_failure_threshold",
        "cooldown_seconds",
        "failure_categories",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelHealthError("model health policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-health-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("expected_response") != "KRCN_HEALTH_OK"
    ):
        raise ModelHealthError("model health policy schema is invalid")
    integers = (
        payload.get("policy_revision"),
        payload.get("probe_suite_revision"),
        payload.get("timeout_seconds"),
        payload.get("maximum_latency_ms"),
        payload.get("quarantine_failure_threshold"),
        payload.get("cooldown_seconds"),
    )
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in integers):
        raise ModelHealthError("model health policy numbers are invalid")
    if not 1 <= int(payload["timeout_seconds"]) <= 300:
        raise ModelHealthError("model health timeout is invalid")
    if not 1 <= int(payload["maximum_latency_ms"]) <= 300000:
        raise ModelHealthError("model health latency bound is invalid")
    for name in ("probe_suite_id", "prompt_id"):
        if not isinstance(payload.get(name), str) or not IDENTIFIER.fullmatch(payload[name]):
            raise ModelHealthError(f"model health {name} is invalid")
    categories = payload.get("failure_categories")
    if (
        not isinstance(categories, list)
        or set(categories) != FAILURE_CATEGORIES
        or len(categories) != len(FAILURE_CATEGORIES)
    ):
        raise ModelHealthError("model health failure categories are invalid")
    if payload.get("invariants") != {
        "synthetic_input_only": True,
        "project_content_included": False,
        "credential_values_included": False,
        "response_content_persisted": False,
        "health_grants_authority": False,
        "remote_probe_requires_provider_approval": True,
    }:
        raise ModelHealthError("model health policy invariants are invalid")
    return ModelHealthPolicy(
        int(payload["policy_revision"]),
        str(payload["probe_suite_id"]),
        int(payload["probe_suite_revision"]),
        str(payload["prompt_id"]),
        str(payload["expected_response"]),
        int(payload["timeout_seconds"]),
        int(payload["maximum_latency_ms"]),
        int(payload["quarantine_failure_threshold"]),
        int(payload["cooldown_seconds"]),
        tuple(sorted(categories)),
        _digest(payload),
    )


@dataclass(frozen=True)
class ModelHealthObservation:
    available: bool
    protocol_valid: bool
    response_parseable: bool
    response_matches: bool
    latency_ms: int
    failure_category: str | None

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(item, bool)
                for item in (
                    self.available,
                    self.protocol_valid,
                    self.response_parseable,
                    self.response_matches,
                )
            )
            or not isinstance(self.latency_ms, int)
            or isinstance(self.latency_ms, bool)
            or not 0 <= self.latency_ms <= 300000
            or self.failure_category not in FAILURE_CATEGORIES | {None}
        ):
            raise ModelHealthError("model health observation is invalid")
        passed = (
            self.available
            and self.protocol_valid
            and self.response_parseable
            and self.response_matches
        )
        if passed != (self.failure_category is None):
            raise ModelHealthError("model health observation outcome is inconsistent")

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "protocol_valid": self.protocol_valid,
            "response_parseable": self.response_parseable,
            "response_matches": self.response_matches,
            "latency_ms": self.latency_ms,
            "failure_category": self.failure_category,
            "response_content_included": False,
        }


class ModelHealthProbe(Protocol):
    def probe(
        self,
        model: Mapping[str, object],
        policy: ModelHealthPolicy,
        authorization: ProviderAuthorization,
    ) -> ModelHealthObservation: ...


HealthTransport = Callable[[str, bytes, str, str, int, str], object]


def _http_transport(
    endpoint: str,
    api_key: bytes,
    model_id: str,
    prompt: str,
    timeout_seconds: int,
    modality: str,
) -> object:
    try:
        credential = api_key.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ModelHealthError("model health credential encoding is invalid") from exc
    request_payload = (
        {"model": model_id, "input": [prompt], "encoding_format": "float"}
        if modality == "embedding"
        else {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 16,
        }
    )
    body = json.dumps(
        request_payload,
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + (
            "/embeddings" if modality == "embedding" else "/chat/completions"
        ),
        data=body,
        headers={
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "krcn-core-model-health",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return {
            "status": response.status,
            "payload": json.loads(response.read().decode("utf-8")),
        }


class OpenAICompatibleModelHealthProbe:
    """Probe a model with synthetic input and never retain its response text."""

    def __init__(
        self,
        secret_resolver: Callable[[str], SecretLease],
        credential_reference: str,
        *,
        transport: HealthTransport | None = None,
    ) -> None:
        if not callable(secret_resolver) or not isinstance(credential_reference, str) or not credential_reference:
            raise ModelHealthError("model health credential resolver is invalid")
        self._secret_resolver = secret_resolver
        self._credential_reference = credential_reference
        self._transport = transport or _http_transport

    def probe(
        self,
        model: Mapping[str, object],
        policy: ModelHealthPolicy,
        authorization: ProviderAuthorization,
    ) -> ModelHealthObservation:
        if not authorization.approval_verified or not authorization.request.remote:
            raise ModelHealthError("remote model health probe requires provider authorization")
        if authorization.request.provider != model.get("provider_ref"):
            raise ModelHealthError("model health provider authorization is not exact")
        started = time.perf_counter()
        try:
            lease = self._secret_resolver(self._credential_reference)
            response = self._transport(
                authorization.request.endpoint,
                lease.reveal(),
                str(model["model_id"]),
                "Return exactly KRCN_HEALTH_OK and no other text.",
                policy.timeout_seconds,
                "embedding"
                if model.get("modalities") == ["embedding"]
                else "text",
            )
        except SecretProviderError:
            latency = min(int((time.perf_counter() - started) * 1000), 300000)
            return ModelHealthObservation(False, False, False, False, latency, "authentication")
        except urllib.error.HTTPError as exc:
            latency = min(int((time.perf_counter() - started) * 1000), 300000)
            category = "authentication" if exc.code in {401, 403} else "provider-error"
            return ModelHealthObservation(False, False, False, False, latency, category)
        except (urllib.error.URLError, TimeoutError):
            latency = min(int((time.perf_counter() - started) * 1000), 300000)
            return ModelHealthObservation(False, False, False, False, latency, "timeout")
        except (OSError, ValueError, json.JSONDecodeError):
            latency = min(int((time.perf_counter() - started) * 1000), 300000)
            return ModelHealthObservation(False, False, False, False, latency, "provider-error")
        latency = min(int((time.perf_counter() - started) * 1000), 300000)
        if not isinstance(response, dict) or response.get("status") != 200:
            return ModelHealthObservation(True, False, False, False, latency, "protocol")
        payload = response.get("payload")
        if model.get("modalities") == ["embedding"]:
            try:
                vector = payload["data"][0]["embedding"]
            except (KeyError, IndexError, TypeError):
                return ModelHealthObservation(True, True, False, False, latency, "parse")
            valid_vector = bool(
                isinstance(vector, list)
                and vector
                and all(
                    isinstance(item, (int, float)) and not isinstance(item, bool)
                    for item in vector
                )
            )
            return ModelHealthObservation(
                True,
                True,
                valid_vector,
                valid_vector,
                latency,
                None if valid_vector else "parse",
            )
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ModelHealthObservation(True, True, False, False, latency, "parse")
        if not isinstance(content, str):
            return ModelHealthObservation(True, True, False, False, latency, "parse")
        matched = content.strip() == policy.expected_response
        return ModelHealthObservation(
            True,
            True,
            True,
            matched,
            latency,
            None if matched else "mismatch",
        )


def create_model_health_provider_request(
    model: Mapping[str, object],
    *,
    endpoint: str,
    retention_assumptions: str,
    session_id: str,
) -> ProviderRequest:
    parsed = parse_model_inventory_record(dict(model))
    if not parsed["remote"]:
        raise ModelHealthError("local model health adapters are not available")
    return create_provider_request(
        provider=str(parsed["provider_ref"]),
        endpoint=endpoint,
        data_categories=("synthetic-test",),
        operation_scope="model-health",
        retention_assumptions=retention_assumptions,
        session_id=session_id,
        remote=True,
    )


@dataclass(frozen=True)
class ModelHealthActionPlan:
    plan_id: str
    model_ref: str
    inventory_digest: str
    previous_health_revision: int
    provider_request: ProviderRequest
    policy_digest: str
    cooldown_active: bool
    eligible_for_retest: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "model_ref": self.model_ref,
            "inventory_digest": self.inventory_digest,
            "previous_health_revision": self.previous_health_revision,
            "provider_request": self.provider_request.public_summary(),
            "policy_digest": self.policy_digest,
            "cooldown_active": self.cooldown_active,
            "eligible_for_retest": self.eligible_for_retest,
            "synthetic_input_only": True,
            "project_content_included": False,
            "credential_values_included": False,
            "response_content_persisted": False,
            "grants_authority": False,
        }


def health_effective_state(record: Mapping[str, object], now: datetime) -> str:
    parsed = parse_model_health_record(dict(record))
    if parsed["status"] != "quarantined":
        return str(parsed["status"])
    until = _parse_timestamp(parsed["quarantine_until"], "quarantine_until")
    return "cooldown" if _utc(now) < until else "candidate"


def prepare_model_health_action(
    repo_root: Path,
    store: LocalWorkspaceStore,
    model_ref: str,
    *,
    endpoint: str,
    retention_assumptions: str,
    session_id: str,
    now: datetime,
    force_retest: bool = False,
) -> ModelHealthActionPlan:
    if not isinstance(model_ref, str) or not IDENTIFIER.fullmatch(model_ref):
        raise ModelHealthError("model_ref is invalid")
    inventory = store.read("model-inventory", model_ref)
    if inventory is None:
        raise ModelHealthError("model inventory record was not found")
    model = parse_model_inventory_record(inventory.payload)
    if not model["enabled"]:
        raise ModelHealthError("disabled model cannot be health checked")
    modalities = set(model["modalities"])
    if not (
        "text" in modalities
        or modalities == {"embedding"}
    ) or model["supported_workloads"] == ["reranking"]:
        raise ModelHealthError(
            "model health probe adapter does not support this model modality"
        )
    policy = load_model_health_policy(repo_root)
    current = store.read("model-health", model_ref)
    previous_revision = 0
    cooldown_active = False
    if current is not None:
        previous = parse_model_health_record(current.payload)
        previous_revision = current.revision
        cooldown_active = bool(
            previous["inventory_digest"] == model["inventory_digest"]
            and previous["policy_digest"] == policy.policy_digest
            and health_effective_state(previous, now) == "cooldown"
        )
        if cooldown_active and not force_retest:
            raise ModelHealthError("model health cooldown is active")
    request = create_model_health_provider_request(
        model,
        endpoint=endpoint,
        retention_assumptions=retention_assumptions,
        session_id=session_id,
    )
    identity = {
        "model_ref": model_ref,
        "inventory_digest": model["inventory_digest"],
        "previous_health_revision": previous_revision,
        "provider_request_id": request.request_id,
        "policy_digest": policy.policy_digest,
        "force_retest": force_retest,
    }
    return ModelHealthActionPlan(
        _digest(identity),
        model_ref,
        str(model["inventory_digest"]),
        previous_revision,
        request,
        policy.policy_digest,
        cooldown_active,
        not cooldown_active or force_retest,
    )


def build_model_health_record(
    model: Mapping[str, object],
    policy: ModelHealthPolicy,
    observation: ModelHealthObservation,
    *,
    checked_at: datetime,
    previous: Mapping[str, object] | None = None,
) -> dict[str, object]:
    inventory = parse_model_inventory_record(dict(model))
    prior = parse_model_health_record(dict(previous)) if previous is not None else None
    streak_prior = (
        prior
        if prior is not None
        and prior["inventory_digest"] == inventory["inventory_digest"]
        and prior["policy_digest"] == policy.policy_digest
        else None
    )
    passed = (
        observation.failure_category is None
        and observation.latency_ms <= policy.maximum_latency_ms
    )
    failure_category = observation.failure_category
    if observation.failure_category is None and not passed:
        failure_category = "timeout"
    consecutive_failures = (
        0
        if passed
        else int(streak_prior["consecutive_failures"] if streak_prior else 0) + 1
    )
    status = "health-passed" if passed else "health-failed"
    quarantine_until = None
    if not passed and consecutive_failures >= policy.quarantine_failure_threshold:
        status = "quarantined"
        quarantine_until = _timestamp(
            _utc(checked_at) + timedelta(seconds=policy.cooldown_seconds)
        )
    probe_identity = {
        "model_ref": inventory["model_ref"],
        "inventory_digest": inventory["inventory_digest"],
        "probe_suite_id": policy.probe_suite_id,
        "probe_suite_revision": policy.probe_suite_revision,
        "policy_digest": policy.policy_digest,
    }
    result_semantic = {
        "model_ref": inventory["model_ref"],
        "inventory_digest": inventory["inventory_digest"],
        "health_revision": 1 if prior is None else int(prior["health_revision"]) + 1,
        "probe_suite_id": policy.probe_suite_id,
        "probe_suite_revision": policy.probe_suite_revision,
        "policy_digest": policy.policy_digest,
        "checked_at": _timestamp(checked_at),
        "status": status,
        "available": observation.available,
        "protocol_valid": observation.protocol_valid,
        "response_parseable": observation.response_parseable,
        "response_matches": observation.response_matches,
        "latency_ms": observation.latency_ms,
        "failure_category": failure_category,
        "consecutive_failures": consecutive_failures,
        "quarantine_until": quarantine_until,
        "probe_digest": _digest(probe_identity),
    }
    return {
        "schema_ref": "schemas/model-health-record.schema.json",
        "schema_version": 1,
        **result_semantic,
        "result_digest": _digest(result_semantic),
        "invariants": {
            "synthetic_input_only": True,
            "project_content_included": False,
            "credential_values_included": False,
            "response_content_included": False,
            "grants_authority": False,
        },
    }


def parse_model_health_record(payload: object) -> dict[str, object]:
    expected = {
        "schema_ref",
        "schema_version",
        "model_ref",
        "inventory_digest",
        "health_revision",
        "probe_suite_id",
        "probe_suite_revision",
        "policy_digest",
        "checked_at",
        "status",
        "available",
        "protocol_valid",
        "response_parseable",
        "response_matches",
        "latency_ms",
        "failure_category",
        "consecutive_failures",
        "quarantine_until",
        "probe_digest",
        "result_digest",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelHealthError("model health record fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-health-record.schema.json"
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("model_ref"), str)
        or not IDENTIFIER.fullmatch(payload["model_ref"])
        or not isinstance(payload.get("inventory_digest"), str)
        or not SHA256.fullmatch(payload["inventory_digest"])
        or payload.get("status") not in {"health-failed", "health-passed", "quarantined"}
        or payload.get("failure_category") not in FAILURE_CATEGORIES | {None}
    ):
        raise ModelHealthError("model health record identity is invalid")
    for key in ("health_revision", "probe_suite_revision", "latency_ms", "consecutive_failures"):
        value = payload.get(key)
        minimum = 0 if key in {"latency_ms", "consecutive_failures"} else 1
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ModelHealthError("model health record numbers are invalid")
    for key in ("available", "protocol_valid", "response_parseable", "response_matches"):
        if not isinstance(payload.get(key), bool):
            raise ModelHealthError("model health record booleans are invalid")
    if not isinstance(payload.get("probe_suite_id"), str) or not IDENTIFIER.fullmatch(payload["probe_suite_id"]):
        raise ModelHealthError("model health probe suite is invalid")
    for key in ("policy_digest", "probe_digest", "result_digest"):
        if not isinstance(payload.get(key), str) or not SHA256.fullmatch(payload[key]):
            raise ModelHealthError("model health digest is invalid")
    _parse_timestamp(payload.get("checked_at"), "checked_at")
    quarantine_until = payload.get("quarantine_until")
    if (payload["status"] == "quarantined") != (quarantine_until is not None):
        raise ModelHealthError("model health quarantine is inconsistent")
    if quarantine_until is not None:
        _parse_timestamp(quarantine_until, "quarantine_until")
    passed = payload["status"] == "health-passed"
    if passed != (payload["failure_category"] is None) or passed != (
        payload["consecutive_failures"] == 0
    ):
        raise ModelHealthError("model health outcome is inconsistent")
    semantic_keys = (
        "model_ref",
        "inventory_digest",
        "health_revision",
        "probe_suite_id",
        "probe_suite_revision",
        "policy_digest",
        "checked_at",
        "status",
        "available",
        "protocol_valid",
        "response_parseable",
        "response_matches",
        "latency_ms",
        "failure_category",
        "consecutive_failures",
        "quarantine_until",
        "probe_digest",
    )
    if payload["result_digest"] != _digest({key: payload[key] for key in semantic_keys}):
        raise ModelHealthError("model health result digest is invalid")
    expected_probe_digest = _digest(
        {
            "model_ref": payload["model_ref"],
            "inventory_digest": payload["inventory_digest"],
            "probe_suite_id": payload["probe_suite_id"],
            "probe_suite_revision": payload["probe_suite_revision"],
            "policy_digest": payload["policy_digest"],
        }
    )
    if payload["probe_digest"] != expected_probe_digest:
        raise ModelHealthError("model health probe digest is invalid")
    if payload.get("invariants") != {
        "synthetic_input_only": True,
        "project_content_included": False,
        "credential_values_included": False,
        "response_content_included": False,
        "grants_authority": False,
    }:
        raise ModelHealthError("model health invariants are invalid")
    return json.loads(json.dumps(payload, ensure_ascii=False))


def persist_model_health_observation(
    store: LocalWorkspaceStore,
    model: Mapping[str, object],
    policy: ModelHealthPolicy,
    observation: ModelHealthObservation,
    *,
    checked_at: datetime,
) -> dict[str, object]:
    current = store.read("model-health", str(model["model_ref"]))
    previous = current.payload if current is not None else None
    record = build_model_health_record(
        model,
        policy,
        observation,
        checked_at=checked_at,
        previous=previous,
    )
    plan = store.prepare_put(
        "model-health",
        str(model["model_ref"]),
        record,
        expected_revision=0 if current is None else current.revision,
    )
    authorization = authorize_mutation(
        plan.mutation,
        dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
    )
    stored = store.apply_put(plan, authorization)
    return {
        **parse_model_health_record(stored.payload),
        "effective_state": health_effective_state(stored.payload, checked_at),
    }


def list_model_health(
    repo_root: Path,
    store: LocalWorkspaceStore,
    *,
    now: datetime,
) -> tuple[dict[str, object], ...]:
    results = []
    policy = load_model_health_policy(repo_root)
    for stored in store.list_records("model-health"):
        record = parse_model_health_record(stored.payload)
        inventory = store.read("model-inventory", str(record["model_ref"]))
        current = False
        if inventory is not None:
            model = parse_model_inventory_record(inventory.payload)
            current = bool(
                model["inventory_digest"] == record["inventory_digest"]
                and record["policy_digest"] == policy.policy_digest
            )
        results.append(
            {
                "model_ref": record["model_ref"],
                "inventory_digest": record["inventory_digest"],
                "health_revision": record["health_revision"],
                "checked_at": record["checked_at"],
                "status": record["status"],
                "effective_state": (
                    health_effective_state(record, now) if current else "stale"
                ),
                "current": current,
                "latency_ms": record["latency_ms"],
                "failure_category": record["failure_category"],
                "consecutive_failures": record["consecutive_failures"],
                "quarantine_until": record["quarantine_until"],
                "credential_values_included": False,
                "response_content_included": False,
            }
        )
    return tuple(sorted(results, key=lambda item: str(item["model_ref"])))

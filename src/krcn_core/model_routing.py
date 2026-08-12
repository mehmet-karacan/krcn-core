"""Client-neutral model profiles with deterministic safe fallbacks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .embedding_models import EmbeddingModelCatalog, load_embedding_model_catalog
from .foundation import load_json
from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
ROLES = {"planner", "worker", "verifier"}
WORKLOADS = {
    "general",
    "planning",
    "implementation",
    "verification",
    "discovery",
    "embedding",
}
KINDS = {"client-slot", "embedding-profile", "offline"}


class ModelRoutingError(ValueError):
    """Raised when a model route is incomplete or unsafe."""


@dataclass(frozen=True)
class ModelCandidate:
    candidate_ref: str
    kind: str
    model_profile_id: str | None
    model_id: str | None
    remote: bool
    requires_authorization: bool


@dataclass(frozen=True)
class ModelRouteProfile:
    profile_id: str
    workload: str
    preferred_refs: tuple[str, ...]
    fallback_ref: str


@dataclass(frozen=True)
class ModelRoutingPolicy:
    revision: int
    default_profile_id: str
    role_defaults: Mapping[str, str]
    candidates: tuple[ModelCandidate, ...]
    profiles: tuple[ModelRouteProfile, ...]
    policy_digest: str

    def profile(self, profile_id: str) -> ModelRouteProfile:
        selected = next(
            (profile for profile in self.profiles if profile.profile_id == profile_id),
            None,
        )
        if selected is None:
            raise ModelRoutingError("model routing profile was not found")
        return selected

    def profile_for_workload(self, workload: str) -> ModelRouteProfile:
        selected = next(
            (profile for profile in self.profiles if profile.workload == workload),
            None,
        )
        if selected is None:
            raise ModelRoutingError("model routing workload was not found")
        return selected


@dataclass(frozen=True)
class ModelRouteSelection:
    profile_id: str
    workload: str
    selected_ref: str
    selected_model_id: str | None
    selection_basis: str
    preferred_refs: tuple[str, ...]
    skipped_unauthorized_refs: tuple[str, ...]
    policy_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/model-route-selection.schema.json",
            "schema_version": 1,
            "profile_id": self.profile_id,
            "workload": self.workload,
            "selected_ref": self.selected_ref,
            "selected_model_id": self.selected_model_id,
            "selection_basis": self.selection_basis,
            "preferred_refs": list(self.preferred_refs),
            "skipped_unauthorized_refs": list(self.skipped_unauthorized_refs),
            "policy_digest": self.policy_digest,
            "model_selection_grants_authority": False,
            "provider_call_performed": False,
        }


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ModelRoutingError(f"{label} is invalid")
    return value


def _candidate(
    payload: object,
    embedding_catalog: EmbeddingModelCatalog,
) -> ModelCandidate:
    expected = {
        "candidate_ref",
        "kind",
        "model_profile_id",
        "remote",
        "requires_authorization",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelRoutingError("model routing candidate fields are invalid")
    candidate_ref = _identifier(payload.get("candidate_ref"), "candidate_ref")
    kind = payload.get("kind")
    if kind not in KINDS:
        raise ModelRoutingError("model routing candidate kind is invalid")
    profile_id = payload.get("model_profile_id")
    if profile_id is not None:
        profile_id = _identifier(profile_id, "model_profile_id")
    remote = payload.get("remote")
    requires_authorization = payload.get("requires_authorization")
    if not isinstance(remote, bool) or not isinstance(requires_authorization, bool):
        raise ModelRoutingError("model routing candidate booleans are invalid")

    model_id = None
    if kind == "embedding-profile":
        if profile_id != candidate_ref or not remote or not requires_authorization:
            raise ModelRoutingError("remote embedding candidate boundary is invalid")
        model_id = embedding_catalog.profile(profile_id).model_id
    elif profile_id is not None:
        raise ModelRoutingError("only embedding candidates may reference a model profile")
    elif kind == "offline" and (remote or requires_authorization):
        raise ModelRoutingError("offline model candidate must remain local")
    elif kind == "client-slot" and (remote or requires_authorization):
        raise ModelRoutingError("client slots must not imply provider authority")
    return ModelCandidate(
        candidate_ref,
        str(kind),
        profile_id,
        model_id,
        remote,
        requires_authorization,
    )


def _profile(payload: object) -> ModelRouteProfile:
    expected = {"profile_id", "workload", "preferred_refs", "fallback_ref"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelRoutingError("model routing profile fields are invalid")
    profile_id = _identifier(payload.get("profile_id"), "profile_id")
    workload = payload.get("workload")
    if workload not in WORKLOADS:
        raise ModelRoutingError("model routing workload is invalid")
    refs = payload.get("preferred_refs")
    if (
        not isinstance(refs, list)
        or not refs
        or any(not isinstance(item, str) for item in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ModelRoutingError("model routing preferences are invalid")
    preferred_refs = tuple(_identifier(item, "preferred_ref") for item in refs)
    fallback_ref = _identifier(payload.get("fallback_ref"), "fallback_ref")
    if preferred_refs[-1] != fallback_ref:
        raise ModelRoutingError("model routing fallback must be the final preference")
    return ModelRouteProfile(
        profile_id,
        str(workload),
        preferred_refs,
        fallback_ref,
    )


def parse_model_routing_policy(
    payload: object,
    embedding_catalog: EmbeddingModelCatalog,
) -> ModelRoutingPolicy:
    expected = {
        "schema_ref",
        "schema_version",
        "revision",
        "default_profile_id",
        "role_defaults",
        "candidates",
        "profiles",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelRoutingError("model routing policy fields are invalid")
    if payload.get("schema_ref") != "schemas/model-routing-policy.schema.json":
        raise ModelRoutingError("model routing schema_ref is invalid")
    if payload.get("schema_version") != 1:
        raise ModelRoutingError("model routing schema_version must be 1")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ModelRoutingError("model routing revision is invalid")
    default_profile_id = _identifier(
        payload.get("default_profile_id"), "default_profile_id"
    )
    role_defaults = payload.get("role_defaults")
    if not isinstance(role_defaults, dict) or set(role_defaults) != ROLES:
        raise ModelRoutingError("model routing role defaults are invalid")
    normalized_roles = {
        role: _identifier(role_defaults[role], f"{role} profile")
        for role in sorted(ROLES)
    }
    candidate_payloads = payload.get("candidates")
    profile_payloads = payload.get("profiles")
    if not isinstance(candidate_payloads, list) or not isinstance(profile_payloads, list):
        raise ModelRoutingError("model routing candidates and profiles must be lists")
    candidates = tuple(_candidate(item, embedding_catalog) for item in candidate_payloads)
    profiles = tuple(_profile(item) for item in profile_payloads)
    if len({item.candidate_ref for item in candidates}) != len(candidates):
        raise ModelRoutingError("model routing candidate refs must be unique")
    if len({item.profile_id for item in profiles}) != len(profiles):
        raise ModelRoutingError("model routing profile ids must be unique")
    if len({item.workload for item in profiles}) != len(profiles):
        raise ModelRoutingError("model routing workloads must be unique")
    by_candidate = {item.candidate_ref: item for item in candidates}
    by_profile = {item.profile_id: item for item in profiles}
    if default_profile_id not in by_profile or any(
        profile_id not in by_profile for profile_id in normalized_roles.values()
    ):
        raise ModelRoutingError("model routing profile reference was not found")
    if set(profile.workload for profile in profiles) != WORKLOADS:
        raise ModelRoutingError("model routing workload coverage is incomplete")
    for profile in profiles:
        if any(ref not in by_candidate for ref in profile.preferred_refs):
            raise ModelRoutingError("model routing candidate reference was not found")
        kinds = {by_candidate[ref].kind for ref in profile.preferred_refs}
        if profile.workload == "embedding":
            if kinds - {"embedding-profile", "offline"}:
                raise ModelRoutingError("embedding route contains a client model slot")
            remote_refs = tuple(
                item.profile_id for item in embedding_catalog.remote_order
            )
            if profile.preferred_refs[:-1] != remote_refs:
                raise ModelRoutingError("embedding route disagrees with its model catalog")
            if profile.fallback_ref != embedding_catalog.offline_fallback_id:
                raise ModelRoutingError("embedding route offline fallback is invalid")
        elif kinds != {"client-slot"} or profile.fallback_ref != "client-default":
            raise ModelRoutingError("generative route fallback is invalid")
    invariants = payload.get("invariants")
    expected_invariants = {
        "model_selection_grants_authority": False,
        "client_default_is_valid_fallback": True,
        "remote_embedding_requires_authorization": True,
        "provider_call_during_resolution": False,
    }
    if invariants != expected_invariants:
        raise ModelRoutingError("model routing invariants are invalid")
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    return ModelRoutingPolicy(
        revision,
        default_profile_id,
        normalized_roles,
        candidates,
        profiles,
        digest,
    )


def load_model_routing_policy(repo_root: Path) -> ModelRoutingPolicy:
    catalog = load_embedding_model_catalog(repo_root)
    return parse_model_routing_policy(
        load_json(repo_root / "config" / "model-routing.json"),
        catalog,
    )


def resolve_model_route(
    policy: ModelRoutingPolicy,
    *,
    workload: str | None = None,
    role: str | None = None,
    available_bindings: Mapping[str, str] | None = None,
    authorized_refs: tuple[str, ...] = (),
) -> ModelRouteSelection:
    if (workload is None) == (role is None):
        raise ModelRoutingError("provide exactly one workload or role")
    if role is not None:
        if role not in ROLES:
            raise ModelRoutingError("model routing role is invalid")
        profile = policy.profile(policy.role_defaults[role])
    else:
        if workload not in WORKLOADS:
            raise ModelRoutingError("model routing workload is invalid")
        profile = policy.profile_for_workload(str(workload))
    bindings = dict(available_bindings or {})
    candidates = {item.candidate_ref: item for item in policy.candidates}
    if any(ref not in candidates for ref in bindings):
        raise ModelRoutingError("available model binding is not declared")
    if any(
        not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id)
        for model_id in bindings.values()
    ):
        raise ModelRoutingError("available model id is invalid")
    if len(set(authorized_refs)) != len(authorized_refs) or any(
        ref not in candidates for ref in authorized_refs
    ):
        raise ModelRoutingError("authorized model refs are invalid")
    authorized = set(authorized_refs)
    skipped: list[str] = []
    selected = None
    basis = ""
    for ref in profile.preferred_refs:
        candidate = candidates[ref]
        if (
            candidate.kind == "embedding-profile"
            and ref in bindings
            and bindings[ref] != candidate.model_id
        ):
            raise ModelRoutingError(
                "embedding binding does not match the reviewed model catalog"
            )
        if candidate.requires_authorization and ref in bindings and ref not in authorized:
            skipped.append(ref)
            continue
        if ref in bindings:
            selected = candidate
            basis = (
                "authorized-remote-binding" if candidate.remote else "client-binding"
            )
            break
        if candidate.kind == "client-slot" and ref == "client-default":
            selected = candidate
            basis = "client-default"
            break
        if candidate.kind == "offline":
            selected = candidate
            basis = "offline-fallback"
            break
    if selected is None:
        raise ModelRoutingError("model routing did not produce a safe fallback")
    selected_model_id = bindings.get(selected.candidate_ref, selected.model_id)
    if selected.kind == "offline":
        selected_model_id = selected.candidate_ref
    return ModelRouteSelection(
        profile.profile_id,
        profile.workload,
        selected.candidate_ref,
        selected_model_id,
        basis,
        profile.preferred_refs,
        tuple(skipped),
        policy.policy_digest,
    )

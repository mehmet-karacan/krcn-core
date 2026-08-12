"""Explicit capability-bound registry for runtime component callbacks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable

from .capability_registry import (
    CapabilityRegistry,
    CapabilitySelection,
    select_capability_records,
)
from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
COMPONENT_KINDS = {"adapter", "secret-provider", "skill", "verifier", "worker"}


class RuntimeComponentError(ValueError):
    """Raised when a runtime callback is unregistered or exceeds its declaration."""


@dataclass(frozen=True)
class RuntimeComponentSpec:
    component_id: str
    kind: str
    capability_record_refs: tuple[str, ...]
    capabilities: tuple[str, ...]
    side_effects: tuple[str, ...]
    callback: Callable[..., object]

    def public_summary(self, selection: CapabilitySelection) -> dict[str, object]:
        identity = {
            "component_id": self.component_id,
            "kind": self.kind,
            "capability_record_refs": list(self.capability_record_refs),
            "capabilities": list(self.capabilities),
            "side_effects": list(self.side_effects),
            "selection_digest": selection.selection_digest,
        }
        return {
            **identity,
            "component_digest": hashlib.sha256(canonical_json(identity)).hexdigest(),
            "callback_registered": True,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class RegisteredRuntimeComponent:
    spec: RuntimeComponentSpec
    selection: CapabilitySelection

    def public_summary(self) -> dict[str, object]:
        return self.spec.public_summary(self.selection)


class RuntimeComponentRegistry:
    """Register runtime callbacks without scanning modules, plugins, or the host."""

    def __init__(self, capabilities: CapabilityRegistry) -> None:
        self._capabilities = capabilities
        self._components: dict[str, RegisteredRuntimeComponent] = {}

    def register(self, spec: RuntimeComponentSpec) -> RegisteredRuntimeComponent:
        if not IDENTIFIER.fullmatch(spec.component_id):
            raise RuntimeComponentError("runtime component id is invalid")
        if spec.kind not in COMPONENT_KINDS:
            raise RuntimeComponentError("runtime component kind is invalid")
        if spec.component_id in self._components:
            raise RuntimeComponentError("runtime component is already registered")
        if not callable(spec.callback):
            raise RuntimeComponentError("runtime component callback is invalid")
        if (
            not spec.capabilities
            or len(set(spec.capabilities)) != len(spec.capabilities)
            or len(set(spec.side_effects)) != len(spec.side_effects)
            or not set(spec.side_effects).issubset({"read", "write", "execute", "network"})
        ):
            raise RuntimeComponentError("runtime component declaration is invalid")
        try:
            selection = select_capability_records(
                self._capabilities,
                spec.capability_record_refs,
                spec.capabilities,
            )
        except ValueError as exc:
            raise RuntimeComponentError(str(exc)) from exc
        selected = selection.selected
        kind_matches = {
            "adapter": any(item.kind == "adapter" for item in selected),
            "secret-provider": any(item.kind == "secret-provider" for item in selected),
            "skill": any(item.kind == "skill" for item in selected),
            "worker": any(item.kind == "agent" and item.role == "worker" for item in selected),
            "verifier": any(item.kind == "agent" and item.role == "verifier" for item in selected),
        }
        if not kind_matches[spec.kind]:
            raise RuntimeComponentError(
                "runtime component lacks a matching capability record kind"
            )
        declared_effects = {
            effect for record in selected for effect in record.side_effects
        }
        if not set(spec.side_effects).issubset(declared_effects):
            raise RuntimeComponentError(
                "runtime component side effects exceed capability records"
            )
        registered = RegisteredRuntimeComponent(spec, selection)
        self._components[spec.component_id] = registered
        return registered

    def require(self, component_id: str, kind: str) -> RegisteredRuntimeComponent:
        component = self._components.get(component_id)
        if component is None:
            raise RuntimeComponentError("runtime component is not explicitly registered")
        if component.spec.kind != kind:
            raise RuntimeComponentError("runtime component kind does not match")
        return component

    def public_catalog(self) -> tuple[dict[str, object], ...]:
        return tuple(
            self._components[item].public_summary()
            for item in sorted(self._components)
        )

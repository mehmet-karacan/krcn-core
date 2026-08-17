"""Stable transport-neutral request, response, and argument contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from .orchestration_service import ORCHESTRATION_OPERATIONS


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
APPLICATION_OPERATIONS = frozenset(
    {
        "installation.inspect",
        "installation.verify",
        "release.diff",
        "release.merge",
        "deployment.rollback",
        "project.list",
        "project.inspect",
        "project.resolve-current",
        "project.resume",
        "client.bootstrap",
        "client.capabilities",
        "client.delegation",
        "execution.coordinate",
        "routing.decide",
        "routing.explain",
        "routing.record",
        "result.normalize-native",
        "result.fan-in",
        "result.trace",
        "model.resolve",
        "model.inventory",
        "model.list",
        "model.health",
        "model.health-list",
        "model.benchmark-suite",
        "model.benchmark-list",
        "model.benchmark-prepare",
        "model.benchmark-execute",
        "model.decide",
        "model.decide-plan",
        "retrieval.evaluate-golden",
        "retrieval.scale-fixture",
        "project.learn",
        "project.integrate",
        "project.index-source-code",
        "project.search-source-code",
        "project.home.resolve",
        "project.home.initialize",
        "project.onboard",
        "project.rescan",
        "project.rebind",
        "integration.select-read-only",
        "portability.backup",
        "portability.restore",
        "portability.migrate-repo-local",
        "portability.migrate-project-home",
        "portability.restore-project-home",
        "portability.merge-project-home",
        "portability.migrate-project-capsules",
        "portability.export-project-capsule",
        "portability.import-project-capsule",
        "knowledge.catalog",
        "knowledge.search-exact",
        "knowledge.search-dependencies",
        "knowledge.search-semantic",
        "knowledge.index-hybrid",
        "knowledge.search-hybrid",
        "context.build",
        "memory.propose",
        "memory.review",
        "memory.persist",
        "memory.lifecycle",
        "memory.hygiene",
        "memory.context-effectiveness",
        "skill.evaluate",
        "skill.plan-change",
        "autonomy.status",
        "autonomy.morning",
        "autonomy.admission",
        "work.item.put",
        "work.list",
        "work.import",
        "work.documents.copy-initial",
        "work.documents.migrate-layout",
        "work.documents.process",
        "work.index-readable",
        "work.index-semantic",
        "work.search",
        "work.query",
        "work.history",
        "research.prepare",
        "research.action",
        "research.import-response",
        "research.status",
        "research.availability",
        "research.dispatch",
        "research.cancel",
        "research.runtime-status",
        "research.resume",
        "runtime.queue.enqueue",
        "runtime.queue.migrate-v2",
        "runtime.queue.claim",
        "runtime.queue.heartbeat",
        "runtime.queue.bind-effect-claim",
        "runtime.queue.bind-effect-receipt",
        "runtime.queue.complete",
        "runtime.queue.fail",
        "runtime.queue.recover",
        "runtime.queue.reconcile",
        "runtime.queue.status",
        "database.oracle.inspect",
        "database.oracle.collect",
        "database.oracle.refresh",
        "database.oracle.status",
        "database.oracle.index",
        "database.oracle.search",
        "database.oracle.dependencies",
        "retrieval.unified",
    }
)
OPERATIONS = APPLICATION_OPERATIONS | frozenset(ORCHESTRATION_OPERATIONS)


class ApplicationServiceError(ValueError):
    """Raised when a shared application request is invalid or unsafe."""


@dataclass(frozen=True)
class ServiceRequest:
    client_kind: str
    operation: str
    arguments: Mapping[str, object]
    apply: bool = False
    expected_plan_id: str | None = None
    approval_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.client_kind, str) or not IDENTIFIER.fullmatch(
            self.client_kind
        ):
            raise ApplicationServiceError("client kind must be a portable identifier")
        if self.operation not in OPERATIONS:
            raise ApplicationServiceError("application operation is invalid")
        if not isinstance(self.arguments, Mapping):
            raise ApplicationServiceError("application arguments must be an object")
        if not isinstance(self.apply, bool):
            raise ApplicationServiceError("apply must be boolean")
        if self.expected_plan_id is not None and not re.fullmatch(
            r"[a-f0-9]{64}", self.expected_plan_id
        ):
            raise ApplicationServiceError("expected plan id is invalid")
        if self.approval_id is not None and not self.approval_id.strip():
            raise ApplicationServiceError("approval id must be non-empty")
        if not self.apply and self.expected_plan_id is not None:
            raise ApplicationServiceError(
                "expected plan evidence may only be supplied when applying"
            )
        try:
            json.dumps(dict(self.arguments), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ApplicationServiceError(
                "application arguments must be JSON-compatible"
            ) from exc

    @property
    def request_id(self) -> str:
        identity = {
            "client_kind": self.client_kind,
            "operation": self.operation,
            "arguments": dict(self.arguments),
            "apply": self.apply,
            "expected_plan_id": self.expected_plan_id,
            "approval_supplied": self.approval_id is not None,
        }
        return hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class ServiceResponse:
    request_id: str
    operation: str
    status: str
    data: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "request_id": self.request_id,
            "operation": self.operation,
            "status": self.status,
            "data": dict(self.data),
        }


def check_arguments(
    arguments: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = required - set(arguments)
    extra = set(arguments) - allowed
    if missing:
        raise ApplicationServiceError(
            "missing application arguments: " + ", ".join(sorted(missing))
        )
    if extra:
        raise ApplicationServiceError(
            "unexpected application arguments: " + ", ".join(sorted(extra))
        )


def string_argument(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApplicationServiceError(f"{name} must be a non-empty string")
    return value


def text_argument(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ApplicationServiceError(f"{name} must be a string")
    return value


def identifier_argument(arguments: Mapping[str, object], name: str) -> str:
    value = string_argument(arguments, name)
    if not IDENTIFIER.fullmatch(value):
        raise ApplicationServiceError(f"{name} must be a portable identifier")
    return value


def object_argument(arguments: Mapping[str, object], name: str) -> dict[str, object]:
    value = arguments.get(name)
    if not isinstance(value, dict):
        raise ApplicationServiceError(f"{name} must be an object")
    return dict(value)


def reviewed_identity_decisions_argument(
    arguments: Mapping[str, object],
) -> dict[str, str]:
    value = arguments.get("reviewed_identity_decisions", {})
    if not isinstance(value, dict):
        raise ApplicationServiceError(
            "reviewed_identity_decisions must be an object"
        )
    decisions: dict[str, str] = {}
    for key, decision in value.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key)
            or decision not in {"request", "defect", "exclude"}
        ):
            raise ApplicationServiceError(
                "reviewed identity decisions must map portable keys to request, defect, or exclude"
            )
        decisions[key] = decision
    return decisions


def string_tuple_argument(
    arguments: Mapping[str, object],
    name: str,
) -> tuple[str, ...]:
    value = arguments.get(name)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ApplicationServiceError(f"{name} must be a non-empty string list")
    result = tuple(item.strip() for item in value)
    if len(set(result)) != len(result):
        raise ApplicationServiceError(f"{name} must contain unique values")
    return result


def nonnegative_integer_argument(
    arguments: Mapping[str, object],
    name: str,
) -> int:
    value = arguments.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApplicationServiceError(f"{name} must not be negative")
    return value

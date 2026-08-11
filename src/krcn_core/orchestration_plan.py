"""Deterministic capability-bound task graph planning."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .capability_registry import CapabilityRecord, CapabilitySelection
from .information_records import canonical_json
from .orchestration_intent import TaskIntent, parse_task_intent


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
CAPABILITY = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
ROLES = {"planner", "worker", "verifier"}
SIDE_EFFECTS = {"read", "write", "execute", "network"}
OWNERSHIP_CLASSES = {"core", "runtime", "user-data", "derived", "secrets", "unmanaged"}
PROVIDER_MODES = {"none": 0, "local": 1, "remote": 2}
APPROVAL_TRIGGERS = {
    "scope-change",
    "user-data-mutation",
    "remote-provider-use",
    "irreversible-effect",
    "policy-change",
    "capability-escalation",
}
ROLLBACK_STRATEGIES = {
    "not-required",
    "restore-checkpoint",
    "rebuild-derived",
    "manual",
}
SENSITIVE_TEXT = re.compile(
    r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*[:=]|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"
)
MAX_STEPS = 1000


class TaskPlanError(ValueError):
    """Raised when a task graph is incomplete, cyclic, or over-authorized."""


@dataclass(frozen=True)
class TaskPlanStep:
    step_id: str
    title: str
    role: str
    depends_on: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    capability_record_refs: tuple[str, ...]
    side_effects: tuple[str, ...]
    ownership_impacts: tuple[str, ...]
    provider_mode: str
    approval_triggers: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    reversible: bool
    rollback_strategy: str
    step_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "role": self.role,
            "depends_on": list(self.depends_on),
            "required_capabilities": list(self.required_capabilities),
            "capability_record_refs": list(self.capability_record_refs),
            "side_effects": list(self.side_effects),
            "ownership_impacts": list(self.ownership_impacts),
            "provider_mode": self.provider_mode,
            "approval_triggers": list(self.approval_triggers),
            "acceptance_criteria": list(self.acceptance_criteria),
            "verification_requirements": list(self.verification_requirements),
            "reversible": self.reversible,
            "rollback_strategy": self.rollback_strategy,
            "step_digest": self.step_digest,
        }


@dataclass(frozen=True)
class TaskPlan:
    task_id: str
    intent_digest: str
    registry_digest: str
    selection_digest: str
    steps: tuple[TaskPlanStep, ...]
    approval_triggers: tuple[str, ...]
    requires_approval: bool
    plan_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/task-plan.schema.json",
            "schema_version": 1,
            "task_id": self.task_id,
            "intent_digest": self.intent_digest,
            "registry_digest": self.registry_digest,
            "selection_digest": self.selection_digest,
            "steps": [step.as_dict() for step in self.steps],
            "approval_triggers": list(self.approval_triggers),
            "requires_approval": self.requires_approval,
            "grants_execution": False,
            "plan_id": self.plan_id,
        }


def _text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 1000
        or SENSITIVE_TEXT.search(value)
    ):
        raise TaskPlanError(f"{label} is invalid or sensitive")
    return value.strip()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise TaskPlanError(f"{label} must be a portable identifier")
    return value


def _unique_strings(value: object, allowed: set[str] | re.Pattern[str], label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise TaskPlanError(f"{label} must be a unique string list")
    if isinstance(allowed, set):
        if any(item not in allowed for item in value):
            raise TaskPlanError(f"{label} contains invalid values")
    elif any(not allowed.fullmatch(item) for item in value):
        raise TaskPlanError(f"{label} contains invalid values")
    return tuple(sorted(value))


def _step_digest(payload: Mapping[str, object]) -> str:
    identity = dict(payload)
    identity.pop("step_digest", None)
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def _selected_by_id(selection: CapabilitySelection) -> dict[str, CapabilityRecord]:
    return {record.record_id: record for record in selection.selected}


def _parse_step(
    payload: object,
    selected: Mapping[str, CapabilityRecord],
    intent: TaskIntent,
) -> TaskPlanStep:
    expected = {
        "step_id",
        "title",
        "role",
        "depends_on",
        "required_capabilities",
        "capability_record_refs",
        "side_effects",
        "ownership_impacts",
        "provider_mode",
        "approval_triggers",
        "acceptance_criteria",
        "verification_requirements",
        "reversible",
        "rollback_strategy",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise TaskPlanError("task plan step fields are invalid")
    step_id = _identifier(payload.get("step_id"), "step_id")
    title = _text(payload.get("title"), "step title")
    role = payload.get("role")
    if role not in ROLES:
        raise TaskPlanError("task plan role is invalid")
    depends_on = _unique_strings(payload.get("depends_on"), IDENTIFIER, "depends_on")
    if step_id in depends_on:
        raise TaskPlanError("task plan step cannot depend on itself")
    required_capabilities = _unique_strings(
        payload.get("required_capabilities"), CAPABILITY, "required_capabilities"
    )
    if not required_capabilities:
        raise TaskPlanError("task plan step requires a capability")
    record_refs = _unique_strings(
        payload.get("capability_record_refs"), IDENTIFIER, "capability_record_refs"
    )
    if not record_refs:
        raise TaskPlanError("task plan step requires explicit capability records")
    try:
        records = tuple(selected[item] for item in record_refs)
    except KeyError as exc:
        raise TaskPlanError("task plan references an unselected capability record") from exc
    agent_roles = {item.role for item in records if item.kind == "agent"}
    if role not in agent_roles:
        raise TaskPlanError("task plan step lacks its exact agent role record")
    provided = {item for record in records for item in record.capabilities}
    if not set(required_capabilities).issubset(provided):
        raise TaskPlanError("task plan step capability is not provided")
    side_effects = _unique_strings(payload.get("side_effects"), SIDE_EFFECTS, "side_effects")
    if role != "worker" and "write" in side_effects:
        raise TaskPlanError("only worker steps may write")
    declared_effects = {item for record in records for item in record.side_effects}
    if not set(side_effects).issubset(declared_effects):
        raise TaskPlanError("task plan step exceeds declared side effects")
    ownership_impacts = _unique_strings(
        payload.get("ownership_impacts"), OWNERSHIP_CLASSES, "ownership_impacts"
    )
    declared_ownership = {
        item
        for record in records
        for item in (
            record.write_ownership if "write" in side_effects else record.read_ownership
        )
    }
    if not set(ownership_impacts).issubset(declared_ownership):
        raise TaskPlanError("task plan step exceeds declared ownership access")
    if not set(ownership_impacts).issubset(set(intent.ownership_impact)):
        raise TaskPlanError("task plan step exceeds intent ownership impact")
    provider_mode = payload.get("provider_mode")
    if provider_mode not in PROVIDER_MODES:
        raise TaskPlanError("task plan provider_mode is invalid")
    required_provider_rank = max(PROVIDER_MODES[item.provider_mode] for item in records)
    if PROVIDER_MODES[str(provider_mode)] != required_provider_rank:
        raise TaskPlanError("task plan provider mode does not match selected records")
    approval_triggers = _unique_strings(
        payload.get("approval_triggers"), APPROVAL_TRIGGERS, "approval_triggers"
    )
    declared_triggers = {item for record in records for item in record.approval_triggers}
    required_triggers = declared_triggers - {
        "user-data-mutation",
        "remote-provider-use",
        "irreversible-effect",
    }
    if "write" in side_effects and "user-data" in ownership_impacts:
        required_triggers.add("user-data-mutation")
    if provider_mode == "remote":
        required_triggers.add("remote-provider-use")
    reversible = payload.get("reversible")
    if not isinstance(reversible, bool):
        raise TaskPlanError("task plan reversible must be boolean")
    if not reversible:
        required_triggers.add("irreversible-effect")
    if not required_triggers.issubset(set(approval_triggers)):
        raise TaskPlanError("task plan step omits required approval triggers")
    rollback_strategy = payload.get("rollback_strategy")
    if rollback_strategy not in ROLLBACK_STRATEGIES:
        raise TaskPlanError("task plan rollback strategy is invalid")
    if reversible and "write" in side_effects and rollback_strategy == "not-required":
        raise TaskPlanError("reversible write step requires rollback strategy")
    if not reversible and rollback_strategy != "manual":
        raise TaskPlanError("irreversible step requires manual rollback declaration")
    accepted = {item.value for item in intent.acceptance_criteria}
    acceptance = _unique_strings(
        payload.get("acceptance_criteria"), accepted, "acceptance_criteria"
    )
    verification_values = {item.value for item in intent.verification_requirements}
    verification = _unique_strings(
        payload.get("verification_requirements"),
        verification_values,
        "verification_requirements",
    )
    normalized = {
        "step_id": step_id,
        "title": title,
        "role": role,
        "depends_on": list(depends_on),
        "required_capabilities": list(required_capabilities),
        "capability_record_refs": list(record_refs),
        "side_effects": list(side_effects),
        "ownership_impacts": list(ownership_impacts),
        "provider_mode": provider_mode,
        "approval_triggers": list(approval_triggers),
        "acceptance_criteria": list(acceptance),
        "verification_requirements": list(verification),
        "reversible": reversible,
        "rollback_strategy": rollback_strategy,
    }
    return TaskPlanStep(
        step_id,
        title,
        str(role),
        depends_on,
        required_capabilities,
        record_refs,
        side_effects,
        ownership_impacts,
        str(provider_mode),
        approval_triggers,
        acceptance,
        verification,
        reversible,
        str(rollback_strategy),
        _step_digest(normalized),
    )


def _topological_steps(steps: Iterable[TaskPlanStep]) -> tuple[TaskPlanStep, ...]:
    by_id = {step.step_id: step for step in steps}
    if len(by_id) == 0:
        raise TaskPlanError("task plan must contain steps")
    if any(dep not in by_id for step in by_id.values() for dep in step.depends_on):
        raise TaskPlanError("task plan dependency was not found")
    pending = {step_id: set(step.depends_on) for step_id, step in by_id.items()}
    ordered = []
    while pending:
        ready = sorted(step_id for step_id, deps in pending.items() if not deps)
        if not ready:
            raise TaskPlanError("task plan dependency graph contains a cycle")
        for step_id in ready:
            ordered.append(by_id[step_id])
            pending.pop(step_id)
            for dependencies in pending.values():
                dependencies.discard(step_id)
    return tuple(ordered)


def _ancestors(step_id: str, by_id: Mapping[str, TaskPlanStep]) -> set[str]:
    found: set[str] = set()
    pending = list(by_id[step_id].depends_on)
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(by_id[current].depends_on)
    return found


def create_task_plan(
    intent: TaskIntent,
    selection: CapabilitySelection,
    step_payloads: Iterable[Mapping[str, object]],
) -> TaskPlan:
    intent = parse_task_intent(intent.as_dict())
    if intent.clarification_required or intent.status != "ready":
        raise TaskPlanError("task intent requires clarification before planning")
    selected = _selected_by_id(selection)
    raw_steps = tuple(step_payloads)
    if not raw_steps or len(raw_steps) > MAX_STEPS:
        raise TaskPlanError("task plan step count is invalid")
    steps = tuple(_parse_step(payload, selected, intent) for payload in raw_steps)
    if len({step.step_id for step in steps}) != len(steps):
        raise TaskPlanError("task plan step ids must be unique")
    ordered = _topological_steps(steps)
    by_id = {step.step_id: step for step in ordered}
    workers = {step.step_id for step in ordered if step.role == "worker"}
    verifiers = tuple(step for step in ordered if step.role == "verifier")
    if not workers or not verifiers:
        raise TaskPlanError("task plan requires worker and verifier steps")
    covered_workers = {
        worker
        for verifier in verifiers
        for worker in workers & _ancestors(verifier.step_id, by_id)
    }
    if covered_workers != workers:
        raise TaskPlanError("every worker step must be covered by verification")
    expected_acceptance = {item.value for item in intent.acceptance_criteria}
    covered_acceptance = {
        item for step in verifiers for item in step.acceptance_criteria
    }
    expected_verification = {item.value for item in intent.verification_requirements}
    covered_verification = {
        item for step in verifiers for item in step.verification_requirements
    }
    if covered_acceptance != expected_acceptance:
        raise TaskPlanError("verifier steps do not cover all acceptance criteria")
    if covered_verification != expected_verification:
        raise TaskPlanError("verifier steps do not cover all verification requirements")
    triggers = tuple(
        sorted({item for step in ordered for item in step.approval_triggers})
    )
    identity = {
        "task_id": intent.task_id,
        "intent_digest": intent.intent_digest,
        "registry_digest": selection.registry_digest,
        "selection_digest": selection.selection_digest,
        "steps": [step.as_dict() for step in ordered],
        "approval_triggers": list(triggers),
        "requires_approval": bool(triggers),
        "grants_execution": False,
    }
    plan_id = hashlib.sha256(canonical_json(identity)).hexdigest()
    return TaskPlan(
        intent.task_id,
        intent.intent_digest,
        selection.registry_digest,
        selection.selection_digest,
        ordered,
        triggers,
        bool(triggers),
        plan_id,
    )

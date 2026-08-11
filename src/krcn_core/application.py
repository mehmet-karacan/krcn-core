"""Transport-neutral application services shared by every KRCN client."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .adapter_gate import (
    AdapterApproval,
    authorize_adapter_operation,
    prepare_adapter_operation,
)
from .discovery import (
    LOCAL_DISCOVERY_ADAPTER,
    discover_local_source,
    load_discovery_policy,
)
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationAuthorization,
    authorize_mutation,
)
from .onboarding import (
    OnboardingRequest,
    apply_read_only_onboarding,
    prepare_read_only_onboarding,
)
from .policies import load_user_policies
from .rescan import apply_rescan, prepare_rescan
from .source_bindings import SourceBinding, parse_source_binding


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
OPERATIONS = {
    "project.list",
    "project.inspect",
    "project.onboard",
    "project.rescan",
}


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


def _check_arguments(
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


def _string_argument(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApplicationServiceError(f"{name} must be a non-empty string")
    return value


def _text_argument(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ApplicationServiceError(f"{name} must be a string")
    return value


def _identifier_argument(arguments: Mapping[str, object], name: str) -> str:
    value = _string_argument(arguments, name)
    if not IDENTIFIER.fullmatch(value):
        raise ApplicationServiceError(f"{name} must be a portable identifier")
    return value


class KrcnApplicationService:
    """Expose one policy-preserving contract to CLI, SDK, MCP, and plugins."""

    def __init__(
        self,
        repo_root: Path,
        store: LocalWorkspaceStore,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._store = store

    def execute(self, request: ServiceRequest) -> ServiceResponse:
        handlers = {
            "project.list": self._list_projects,
            "project.inspect": self._inspect_project,
            "project.onboard": self._onboard_project,
            "project.rescan": self._rescan_project,
        }
        status, data = handlers[request.operation](request)
        return ServiceResponse(
            request_id=request.request_id,
            operation=request.operation,
            status=status,
            data=data,
        )

    def _list_projects(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set())
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        projects = []
        for record in self._store.list_records("projects"):
            projects.append(
                {
                    "project_id": record.record_id,
                    "name": record.payload.get("name"),
                    "status": record.payload.get("status"),
                    "revision": record.revision,
                }
            )
        return "ok", {"projects": projects}

    def _inspect_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        project_id = _identifier_argument(request.arguments, "project_id")
        project = self._store.read("projects", project_id)
        if project is None:
            raise ApplicationServiceError("project is not registered")
        source_refs = project.payload.get("source_refs", [])
        if not isinstance(source_refs, list):
            raise ApplicationServiceError("project source references are invalid")
        bindings = []
        source_states = []
        for binding_id in source_refs:
            if not isinstance(binding_id, str):
                raise ApplicationServiceError("project source reference is invalid")
            binding_record = self._store.read("source-bindings", binding_id)
            if binding_record is None:
                raise ApplicationServiceError("project source binding is missing")
            binding = parse_source_binding(binding_record.payload)
            bindings.append(binding.public_summary())
            state = self._store.read("source-states", binding_id)
            if state is not None:
                source_states.append(
                    {
                        "binding_id": binding_id,
                        "record_revision": state.revision,
                        "binding_revision": state.payload["binding_revision"],
                        "root_digest": state.payload["root_digest"],
                        "file_count": len(state.payload["files"]),
                        "technologies": list(state.payload["technologies"]),
                    }
                )
        project_fields = (
            "project_id",
            "name",
            "description",
            "source_refs",
            "technologies",
            "modules",
            "skill_refs",
            "status",
            "created_at",
            "last_scanned_at",
        )
        project_summary = {
            key: project.payload[key]
            for key in project_fields
            if key in project.payload
        }
        project_summary["record_revision"] = project.revision
        return "ok", {
            "project": project_summary,
            "source_bindings": bindings,
            "source_states": source_states,
        }

    def _onboard_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "workspace_id",
                "project_id",
                "binding_id",
                "project_name",
                "description",
                "source_root",
            },
            optional={"policy_refs", "expected_workspace_revision"},
        )
        policy_refs = request.arguments.get("policy_refs", [])
        if not isinstance(policy_refs, list) or any(
            not isinstance(item, str) or not IDENTIFIER.fullmatch(item)
            for item in policy_refs
        ):
            raise ApplicationServiceError("policy_refs must contain portable identifiers")
        expected_revision = request.arguments.get("expected_workspace_revision", 0)
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise ApplicationServiceError(
                "expected_workspace_revision must not be negative"
            )
        onboarding_request = OnboardingRequest(
            workspace_id=_identifier_argument(request.arguments, "workspace_id"),
            project_id=_identifier_argument(request.arguments, "project_id"),
            binding_id=_identifier_argument(request.arguments, "binding_id"),
            project_name=_string_argument(request.arguments, "project_name"),
            description=_text_argument(request.arguments, "description"),
            source_root=Path(_string_argument(request.arguments, "source_root")),
            policy_refs=tuple(policy_refs),
            expected_workspace_revision=expected_revision,
        )
        plan = prepare_read_only_onboarding(self._store, onboarding_request)
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_record_plans(
            request,
            plan.plan_id,
            plan.record_plans,
        )
        result = apply_read_only_onboarding(self._store, plan, authorizations)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _binding_for_project(
        self,
        project_id: str,
        requested_binding_id: object,
    ) -> SourceBinding:
        project = self._store.read("projects", project_id)
        if project is None:
            raise ApplicationServiceError("project is not registered")
        source_refs = project.payload.get("source_refs")
        if not isinstance(source_refs, list) or any(
            not isinstance(item, str) for item in source_refs
        ):
            raise ApplicationServiceError("project source references are invalid")
        if requested_binding_id is None:
            if len(source_refs) != 1:
                raise ApplicationServiceError(
                    "binding_id is required when a project has multiple sources"
                )
            binding_id = source_refs[0]
        else:
            if (
                not isinstance(requested_binding_id, str)
                or not IDENTIFIER.fullmatch(requested_binding_id)
            ):
                raise ApplicationServiceError(
                    "binding_id must be a portable identifier"
                )
            binding_id = requested_binding_id
            if binding_id not in source_refs:
                raise ApplicationServiceError(
                    "source binding is not registered for this project"
                )
        binding_record = self._store.read("source-bindings", binding_id)
        if binding_record is None:
            raise ApplicationServiceError("project source binding is missing")
        return parse_source_binding(binding_record.payload)

    def _rescan_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id"},
            optional={"binding_id"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        binding = self._binding_for_project(
            project_id,
            request.arguments.get("binding_id"),
        )
        policies = load_user_policies(self._store.data_root / "policies")
        adapter_request = prepare_adapter_operation(
            LOCAL_DISCOVERY_ADAPTER,
            binding,
            "discover",
            policies,
        )
        adapter_approval = None
        if request.approval_id is not None:
            adapter_approval = AdapterApproval(
                request_id=adapter_request.request_id,
                approval_id=request.approval_id,
                approved=True,
            )
        adapter_authorization = authorize_adapter_operation(
            adapter_request,
            adapter_approval,
        )
        discovery = discover_local_source(
            binding,
            load_discovery_policy(self._repo_root),
            adapter_authorization,
        )
        plan = prepare_rescan(self._store, binding, discovery)
        if not request.apply:
            return "planned", {
                "plan": plan.public_summary(),
                "discovery": {
                    "file_count": len(discovery.files),
                    "technologies": list(discovery.technologies),
                    "skipped": dict(discovery.skipped),
                },
                "applied": False,
            }
        authorizations = self._authorize_record_plans(
            request,
            plan.plan_id,
            plan.record_plans,
        )
        result = apply_rescan(self._store, plan, authorizations)
        return "applied", {
            "plan": plan.public_summary(),
            "record_count": len(result.records),
            "applied": True,
        }

    @staticmethod
    def _authorize_record_plans(
        request: ServiceRequest,
        plan_id: str,
        record_plans: tuple[RecordWritePlan, ...],
    ) -> dict[str, MutationAuthorization]:
        if request.expected_plan_id != plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        if any(item.mutation.approval_required for item in record_plans) and (
            request.approval_id is None
        ):
            raise ApplicationServiceError("user-data mutation requires approval id")
        authorizations = {}
        for item in record_plans:
            mutation = item.mutation
            approval = None
            if mutation.approval_required:
                approval = ApprovalEvidence(
                    plan_id=mutation.plan_id,
                    approval_id=request.approval_id or "",
                    approved=True,
                )
            authorizations[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, verified=True),
                approval=approval,
            )
        return authorizations

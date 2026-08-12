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
from .deployment import authorize_deployment_plan, prepare_deployment_plan
from .dependency_retrieval import (
    parse_dependency_query,
    parse_information_relation,
    retrieve_dependencies,
)
from .derived_actions import DerivedActionHandlerRegistry
from .exact_retrieval import parse_exact_retrieval_query, retrieve_exact
from .foundation import load_json
from .information_records import parse_information_record, record_is_stale
from .integrations import parse_integration_metadata
from .hybrid_retrieval import (
    apply_hybrid_index,
    parse_hybrid_query,
    prepare_hybrid_index,
    retrieve_hybrid,
)
from .intent_routing import project_learning_route
from .installation import (
    inspect_installation,
    load_installation_state,
)
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .knowledge_catalog import CatalogEntry, InformationCatalog, build_information_catalog
from .context_builder import (
    build_context_package,
    context_candidate_from_entry,
    parse_context_build_request,
)
from .client_bootstrap import apply_client_bootstrap, prepare_client_bootstrap
from .memory_gate import (
    apply_memory_lifecycle,
    apply_memory_persistence,
    parse_memory_action,
    parse_memory_candidate,
    parse_memory_review,
    prepare_memory_lifecycle,
    prepare_memory_persistence,
)
from .merge_engine import execute_deployment
from .merge_plan import prepare_merge_plan
from .migrations import MigrationHandlerRegistry
from .mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    authorize_mutation,
)
from .onboarding import (
    OnboardingRequest,
    apply_read_only_onboarding,
    prepare_read_only_onboarding,
)
from .orchestration_service import (
    ORCHESTRATION_OPERATIONS,
    OrchestrationApplicationService,
)
from .orchestration_verifier import VerifierHandlerRegistry
from .orchestration_worker import WorkerHandlerRegistry
from .policies import load_user_policies
from .project_learning import apply_project_learning, prepare_project_learning
from .project_learning_intent import parse_project_learning_intent
from .project_context import (
    build_project_resume_summary,
    resolve_current_project,
    unmatched_project_context,
)
from .project_home import choose_project_home, resolve_project_home
from .project_home_initialization import (
    apply_project_home_initialization,
    prepare_project_home_initialization,
)
from .project_home_portability import (
    apply_project_home_migration,
    apply_project_home_restore,
    prepare_project_home_migration,
    prepare_project_home_restore,
)
from .project_home_merge import (
    apply_project_home_merge,
    prepare_project_home_merge,
)
from .portable_backup import apply_portable_backup, prepare_portable_backup
from .portable_restore import apply_portable_restore, prepare_portable_restore
from .provider_gate import ProviderApproval, load_provider_gate_policy
from .rescan import apply_rescan, prepare_rescan
from .release import validate_release_bundle
from .repo_local_migration import (
    apply_repo_local_migration,
    prepare_repo_local_migration,
)
from .release_diff import create_release_diff
from .rollback import (
    apply_rollback,
    authorize_rollback_plan,
    prepare_rollback_plan,
)
from .source_bindings import SourceBinding, parse_source_binding
from .source_rebind import (
    apply_source_rebind,
    candidate_binding,
    prepare_source_rebind,
)
from .semantic_retrieval import (
    RemoteSemanticScorer,
    create_semantic_provider_request,
    parse_semantic_query,
    retrieve_semantic,
)
from .sqlite_reference_runtime import SqliteReferenceRuntime
from .update_effects import DerivedActionRegistry, MigrationRegistry
from .user_home import resolve_user_home
from .verification import verify_installation


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
OPERATIONS = {
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
    "project.learn",
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
} | ORCHESTRATION_OPERATIONS


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


def _object_argument(arguments: Mapping[str, object], name: str) -> dict[str, object]:
    value = arguments.get(name)
    if not isinstance(value, dict):
        raise ApplicationServiceError(f"{name} must be an object")
    return dict(value)


def _nonnegative_integer_argument(
    arguments: Mapping[str, object],
    name: str,
) -> int:
    value = arguments.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApplicationServiceError(f"{name} must not be negative")
    return value


class KrcnApplicationService:
    """Expose one policy-preserving contract to CLI, SDK, MCP, and plugins."""

    def __init__(
        self,
        repo_root: Path,
        store: LocalWorkspaceStore,
        *,
        migration_registry: MigrationRegistry | None = None,
        derived_registry: DerivedActionRegistry | None = None,
        migration_handlers: MigrationHandlerRegistry | None = None,
        derived_handlers: DerivedActionHandlerRegistry | None = None,
        semantic_remote_scorers: Mapping[str, RemoteSemanticScorer] | None = None,
        orchestration_worker_handlers: WorkerHandlerRegistry | None = None,
        orchestration_verifier_handlers: VerifierHandlerRegistry | None = None,
        sqlite_runtime: SqliteReferenceRuntime | None = None,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._store = store
        self._ownership = OwnershipResolver.from_repository(self._repo_root)
        self._migration_registry = migration_registry or MigrationRegistry()
        self._derived_registry = derived_registry or DerivedActionRegistry()
        self._migration_handlers = (
            migration_handlers or MigrationHandlerRegistry()
        )
        self._derived_handlers = (
            derived_handlers or DerivedActionHandlerRegistry()
        )
        scorers = dict(semantic_remote_scorers or {})
        if any(
            not isinstance(provider, str)
            or not IDENTIFIER.fullmatch(provider)
            or not callable(scorer)
            for provider, scorer in scorers.items()
        ):
            raise ApplicationServiceError("semantic remote scorers are invalid")
        self._semantic_remote_scorers = scorers
        self._sqlite_runtime = sqlite_runtime
        self._orchestration = OrchestrationApplicationService(
            self._repo_root,
            self._store,
            worker_handlers=orchestration_worker_handlers,
            verifier_handlers=orchestration_verifier_handlers,
        )

    def execute(self, request: ServiceRequest) -> ServiceResponse:
        if request.operation in ORCHESTRATION_OPERATIONS:
            status, data = self._orchestration.execute(
                request.operation,
                request.arguments,
                apply=request.apply,
                expected_plan_id=request.expected_plan_id,
            )
            return ServiceResponse(
                request_id=request.request_id,
                operation=request.operation,
                status=status,
                data=data,
            )
        handlers = {
            "installation.inspect": self._inspect_installation,
            "installation.verify": self._verify_installation,
            "release.diff": self._diff_release,
            "release.merge": self._merge_release,
            "deployment.rollback": self._rollback_deployment,
            "project.list": self._list_projects,
            "project.inspect": self._inspect_project,
            "project.resolve-current": self._resolve_current_project,
            "project.resume": self._resume_project,
            "client.bootstrap": self._bootstrap_clients,
            "project.learn": self._learn_project,
            "project.home.resolve": self._resolve_project_home,
            "project.home.initialize": self._initialize_project_home,
            "project.onboard": self._onboard_project,
            "project.rescan": self._rescan_project,
            "project.rebind": self._rebind_project,
            "integration.select-read-only": self._select_read_only_integration,
            "portability.backup": self._portable_backup,
            "portability.restore": self._portable_restore,
            "portability.migrate-repo-local": self._migrate_repo_local,
            "portability.migrate-project-home": self._migrate_project_home,
            "portability.restore-project-home": self._restore_project_home,
            "portability.merge-project-home": self._merge_project_home,
            "knowledge.catalog": self._knowledge_catalog,
            "knowledge.search-exact": self._search_exact,
            "knowledge.search-dependencies": self._search_dependencies,
            "knowledge.search-semantic": self._search_semantic,
            "knowledge.index-hybrid": self._index_hybrid,
            "knowledge.search-hybrid": self._search_hybrid,
            "context.build": self._build_context,
            "memory.propose": self._propose_memory,
            "memory.review": self._review_memory,
            "memory.persist": self._persist_memory,
            "memory.lifecycle": self._change_memory_lifecycle,
        }
        status, data = handlers[request.operation](request)
        return ServiceResponse(
            request_id=request.request_id,
            operation=request.operation,
            status=status,
            data=data,
        )

    @staticmethod
    def _absolute_path_argument(
        arguments: Mapping[str, object],
        name: str,
    ) -> Path:
        value = _string_argument(arguments, name)
        path = Path(value)
        if not path.is_absolute():
            raise ApplicationServiceError(f"{name} must be absolute")
        return path.resolve()

    def _inspect_installation(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"installation_root"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        root = self._absolute_path_argument(
            request.arguments,
            "installation_root",
        )
        inspection = inspect_installation(root, self._ownership)
        return "ok", {"inspection": inspection.public_summary()}

    def _verify_installation(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"installation_root"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        root = self._absolute_path_argument(
            request.arguments,
            "installation_root",
        )
        result = verify_installation(root, self._ownership)
        return "ok", {"verification": result.public_summary()}

    def _release_inputs(
        self,
        arguments: Mapping[str, object],
    ):
        root = self._absolute_path_argument(arguments, "installation_root")
        release_root = self._absolute_path_argument(arguments, "release_root")
        trusted_digest = _string_argument(
            arguments,
            "trusted_manifest_sha256",
        )
        state, _ = load_installation_state(root)
        if state is None:
            raise ApplicationServiceError(
                "release operation requires registered installation state"
            )
        bundle = validate_release_bundle(
            release_root,
            self._ownership,
            trusted_manifest_sha256=trusted_digest,
            installed_core_version=state.core_version,
            import_policy=load_json(
                self._repo_root / "config" / "import-policy.json"
            ),
        )
        return root, release_root, state, bundle

    def _diff_release(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "installation_root",
                "release_root",
                "trusted_manifest_sha256",
            },
        )
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        root, _, _, bundle = self._release_inputs(request.arguments)
        release_diff = create_release_diff(root, bundle, self._ownership)
        return "ok", {
            "release": bundle.public_summary(),
            "diff": release_diff.public_summary(),
        }

    def _prepare_release_deployment(
        self,
        arguments: Mapping[str, object],
    ):
        root, release_root, state, bundle = self._release_inputs(arguments)
        release_diff = create_release_diff(root, bundle, self._ownership)
        merge_plan = prepare_merge_plan(
            release_diff,
            state,
            self._ownership,
            self._migration_registry,
            self._derived_registry,
            source_commit=bundle.manifest.source_commit,
        )
        if not merge_plan.has_effects:
            return root, release_root, bundle, release_diff, merge_plan, None
        deployment_plan = prepare_deployment_plan(
            root,
            merge_plan,
            self._ownership,
            self._migration_handlers,
            self._derived_handlers,
        )
        return (
            root,
            release_root,
            bundle,
            release_diff,
            merge_plan,
            deployment_plan,
        )

    def _merge_release(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "installation_root",
                "release_root",
                "trusted_manifest_sha256",
            },
        )
        (
            root,
            release_root,
            bundle,
            release_diff,
            merge_plan,
            deployment_plan,
        ) = self._prepare_release_deployment(request.arguments)
        if deployment_plan is None:
            if request.apply and request.expected_plan_id != merge_plan.plan_id:
                raise ApplicationServiceError(
                    "apply requires the exact plan id returned by a prior dry-run"
                )
            return "ok", {
                "plan": merge_plan.public_summary(),
                "diff": release_diff.public_summary(),
                "applied": False,
                "no_op": True,
            }
        if not request.apply:
            return "planned", {
                "plan": deployment_plan.public_summary(),
                "diff": release_diff.public_summary(),
                "applied": False,
                "no_op": False,
            }
        if request.expected_plan_id != deployment_plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        authorization = authorize_deployment_plan(
            deployment_plan,
            expected_plan_id=request.expected_plan_id,
            approval_id=request.approval_id,
        )
        result = execute_deployment(
            root,
            release_root,
            bundle,
            deployment_plan,
            authorization,
            self._ownership,
        )
        return "applied", {
            "plan": deployment_plan.public_summary(),
            "result": result.public_summary(),
            "applied": True,
            "no_op": False,
        }

    def _rollback_deployment(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"installation_root", "deployment_id"},
        )
        root = self._absolute_path_argument(
            request.arguments,
            "installation_root",
        )
        deployment_id = _identifier_argument(
            request.arguments,
            "deployment_id",
        )
        plan = prepare_rollback_plan(root, deployment_id, self._ownership)
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        authorization = authorize_rollback_plan(
            plan,
            expected_plan_id=request.expected_plan_id,
            approval_id=request.approval_id,
        )
        result = apply_rollback(root, plan, authorization)
        return "applied", {
            "plan": plan.public_summary(),
            "result": result.public_summary(),
            "applied": True,
        }

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

    def _project_context_match(self, request: ServiceRequest):
        _check_arguments(
            request.arguments,
            required={"working_directory"},
            optional={"project_ref", "request_text"},
        )
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        project_ref = (
            _string_argument(request.arguments, "project_ref")
            if "project_ref" in request.arguments
            else None
        )
        request_text = (
            _text_argument(request.arguments, "request_text")
            if "request_text" in request.arguments
            else None
        )
        return resolve_current_project(
            self._store,
            working_directory=self._absolute_path_argument(
                request.arguments,
                "working_directory",
            ),
            project_ref=project_ref,
            request_text=request_text,
        )

    def _resolve_current_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        match = self._project_context_match(request)
        if match is None:
            return "ok", unmatched_project_context()
        return "ok", match.public_summary(self._store)

    def _resume_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        match = self._project_context_match(request)
        if match is None:
            return "ok", {**unmatched_project_context(), "resume": None}
        return "ok", build_project_resume_summary(self._store, match)

    def _bootstrap_clients(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set())
        plan = prepare_client_bootstrap(
            Path.home(),
            self._store.data_root,
            self._ownership,
        )
        if not request.apply:
            status = "planned" if plan.effect_plans else "ok"
            return status, {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "client bootstrap",
        )
        result = apply_client_bootstrap(plan, authorizations)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

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

    def _learn_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"request_text"},
            optional={"source_root"},
        )
        source_root = None
        if "source_root" in request.arguments:
            source_root = self._absolute_path_argument(
                request.arguments,
                "source_root",
            )
        intent = parse_project_learning_intent(
            _string_argument(request.arguments, "request_text"),
            source_root=source_root,
            intent_terms=project_learning_route(self._repo_root).terms,
        )
        plan = prepare_project_learning(self._repo_root, self._store, intent)
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_record_plans(
            request,
            plan.plan_id,
            plan.record_plans,
        )
        result = apply_project_learning(
            self._repo_root,
            self._store,
            plan,
            authorizations,
        )
        return "applied", {
            "plan": plan.public_summary(),
            **result.public_summary(),
            "applied": True,
        }

    def _project_home_resolution(
        self,
        arguments: Mapping[str, object],
    ):
        _check_arguments(
            arguments,
            required={"project_root"},
            optional={"choice", "selected_parent", "explicit_data_root"},
        )
        project_root = self._absolute_path_argument(arguments, "project_root")
        explicit = None
        if "explicit_data_root" in arguments:
            explicit = self._absolute_path_argument(arguments, "explicit_data_root")
        resolution = resolve_project_home(
            project_root,
            explicit_data_root=explicit,
            environ={},
        )
        choice = arguments.get("choice")
        if choice is not None:
            if not isinstance(choice, str):
                raise ApplicationServiceError("project-home choice must be a string")
            selected_parent = None
            if "selected_parent" in arguments:
                selected_parent = self._absolute_path_argument(
                    arguments,
                    "selected_parent",
                )
            resolution = choose_project_home(
                resolution,
                choice,
                selected_parent=selected_parent,
            )
        elif "selected_parent" in arguments:
            raise ApplicationServiceError(
                "selected_parent requires the choose-parent choice"
            )
        return resolution

    def _resolve_project_home(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError("project-home resolution is read-only")
        resolution = self._project_home_resolution(request.arguments)
        if resolution is None:
            return "cancelled", {"cancelled": True}
        status = "choice-required" if resolution.requires_user_choice else "ok"
        return status, {
            "resolution": resolution.as_dict(disclose_path=True),
            "cancelled": False,
        }

    def _initialize_project_home(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        resolution = self._project_home_resolution(request.arguments)
        if resolution is None:
            if request.apply:
                raise ApplicationServiceError("cancelled choice cannot be applied")
            return "cancelled", {"cancelled": True, "applied": False}
        try:
            plan = prepare_project_home_initialization(resolution, self._ownership)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        summary = plan.public_summary(disclose_path=True)
        if not request.apply:
            return "planned", {"plan": summary, "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        if plan.effect_plans and request.approval_id is None:
            raise ApplicationServiceError(
                "project-home initialization requires approval id"
            )
        authorizations = {}
        for mutation in plan.effect_plans:
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
        try:
            result = apply_project_home_initialization(
                plan,
                authorizations,
                self._ownership,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {
            "plan": summary,
            **result.public_summary(),
            "applied": True,
        }

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

    def _rebind_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id", "candidate_root"},
            optional={"binding_id"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        binding = self._binding_for_project(
            project_id,
            request.arguments.get("binding_id"),
        )
        root = self._absolute_path_argument(request.arguments, "candidate_root")
        candidate = candidate_binding(binding, root)
        policies = load_user_policies(self._store.data_root / "policies")
        adapter_request = prepare_adapter_operation(
            LOCAL_DISCOVERY_ADAPTER,
            candidate,
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
        discovery = discover_local_source(
            candidate,
            load_discovery_policy(self._repo_root),
            authorize_adapter_operation(adapter_request, adapter_approval),
        )
        plan = prepare_source_rebind(self._store, binding, root, discovery)
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_record_plans(
            request,
            plan.plan_id,
            plan.record_plans,
        )
        result = apply_source_rebind(
            self._store,
            plan,
            authorizations,
            candidate,
            discovery,
        )
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _select_read_only_integration(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"integration_id", "binding_id", "statement"},
            optional={"maximum_rows"},
        )
        if request.apply:
            raise ApplicationServiceError("read-only integration cannot be applied")
        if self._sqlite_runtime is None:
            raise ApplicationServiceError(
                "SQLite reference runtime is not explicitly registered"
            )
        integration_id = _identifier_argument(request.arguments, "integration_id")
        binding_id = _identifier_argument(request.arguments, "binding_id")
        integration_record = self._store.read("integrations", integration_id)
        binding_record = self._store.read("source-bindings", binding_id)
        if integration_record is None or binding_record is None:
            raise ApplicationServiceError("integration or source binding was not found")
        integration = parse_integration_metadata(dict(integration_record.payload))
        binding = parse_source_binding(dict(binding_record.payload))
        maximum_rows = request.arguments.get("maximum_rows", 1_000)
        if (
            not isinstance(maximum_rows, int)
            or isinstance(maximum_rows, bool)
            or maximum_rows < 1
        ):
            raise ApplicationServiceError("maximum_rows must be positive")
        result = self._sqlite_runtime.execute_select(
            integration,
            binding,
            _string_argument(request.arguments, "statement"),
            load_user_policies(self._store.data_root / "policies"),
            maximum_rows=maximum_rows,
        )
        return "ok", {
            "result": result.public_summary(),
            "component_catalog": self._sqlite_runtime.component_catalog(),
        }

    def _portable_backup(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"archive_path"})
        archive_path = self._absolute_path_argument(request.arguments, "archive_path")
        plan = prepare_portable_backup(
            self._store.data_root,
            archive_path,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        if request.approval_id is None:
            raise ApplicationServiceError("portable backup requires approval id")
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                request.approval_id,
                approved=True,
            ),
        )
        result = apply_portable_backup(plan, authorization)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _portable_restore(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"archive_path"})
        archive_path = self._absolute_path_argument(request.arguments, "archive_path")
        plan = prepare_portable_restore(
            archive_path,
            self._store.data_root,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        if request.approval_id is None:
            raise ApplicationServiceError("portable restore requires approval id")
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                request.approval_id,
                approved=True,
            ),
        )
        result = apply_portable_restore(plan, authorization)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _migrate_repo_local(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"backup_path"})
        backup_path = self._absolute_path_argument(request.arguments, "backup_path")
        plan = prepare_repo_local_migration(
            self._repo_root,
            self._store.data_root,
            backup_path,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        if request.approval_id is None:
            raise ApplicationServiceError("repo-local migration requires approval id")
        authorizations: dict[str, MutationAuthorization] = {}
        for mutation in plan.effect_plans:
            authorizations[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, verified=True),
                approval=ApprovalEvidence(
                    mutation.plan_id,
                    request.approval_id,
                    approved=True,
                ),
            )
        result = apply_repo_local_migration(plan, authorizations)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _migrate_project_home(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"source_home", "project_root", "backup_path", "choice"},
            optional={"selected_parent"},
        )
        resolution = self._project_home_resolution(
            {
                key: value
                for key, value in request.arguments.items()
                if key in {"project_root", "choice", "selected_parent"}
            }
        )
        if resolution is None:
            raise ApplicationServiceError("cancelled migration cannot be planned")
        plan = prepare_project_home_migration(
            self._absolute_path_argument(request.arguments, "source_home"),
            resolution,
            self._absolute_path_argument(request.arguments, "backup_path"),
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "project-home migration",
        )
        result = apply_project_home_migration(plan, authorizations)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _restore_project_home(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"archive_path", "project_root", "choice"},
            optional={"selected_parent"},
        )
        resolution = self._project_home_resolution(
            {
                key: value
                for key, value in request.arguments.items()
                if key in {"project_root", "choice", "selected_parent"}
            }
        )
        if resolution is None:
            raise ApplicationServiceError("cancelled restore cannot be planned")
        plan = prepare_project_home_restore(
            self._absolute_path_argument(request.arguments, "archive_path"),
            resolution,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "project-home restore",
        )
        result = apply_project_home_restore(plan, authorizations)
        return "applied", {"plan": plan.public_summary(), **result}

    def _merge_project_home(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"source_home", "target_home", "backup_directory"},
        )
        target_home = self._absolute_path_argument(request.arguments, "target_home")
        if target_home != self._store.data_root.resolve():
            raise ApplicationServiceError(
                "project-home merge target must equal the active KRCN data root"
            )
        plan = prepare_project_home_merge(
            self._absolute_path_argument(request.arguments, "source_home"),
            target_home,
            self._absolute_path_argument(request.arguments, "backup_directory"),
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "project-home merge",
        )
        result = apply_project_home_merge(plan, authorizations)
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    @staticmethod
    def _authorize_effect_plans(
        request: ServiceRequest,
        plan_id: str,
        effects: tuple[MutationPlan, ...],
        label: str,
    ) -> dict[str, MutationAuthorization]:
        if request.expected_plan_id != plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        if request.approval_id is None:
            raise ApplicationServiceError(f"{label} requires approval id")
        return {
            mutation.plan_id: authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, verified=True),
                approval=ApprovalEvidence(
                    mutation.plan_id,
                    request.approval_id,
                    approved=True,
                ),
            )
            for mutation in effects
        }

    def _information_catalog(self) -> InformationCatalog:
        bindings = tuple(
            parse_source_binding(dict(record.payload))
            for record in self._store.list_records("source-bindings")
        )
        records = tuple(
            parse_information_record(dict(record.payload))
            for collection in ("authoritative-sources", "knowledge")
            for record in self._store.list_records(collection)
        )
        return build_information_catalog(bindings, records)

    def _information_relations(self):
        return tuple(
            parse_information_relation(dict(record.payload))
            for record in self._store.list_records("information-relations")
        )

    def _knowledge_catalog(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set())
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        return "ok", {"catalog": self._information_catalog().as_dict()}

    def _search_exact(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"query"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        query = parse_exact_retrieval_query(
            _object_argument(request.arguments, "query")
        )
        result = retrieve_exact(self._information_catalog(), query)
        return "ok", {"result": result.as_dict()}

    def _search_dependencies(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"query"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        query = parse_dependency_query(
            _object_argument(request.arguments, "query")
        )
        result = retrieve_dependencies(
            self._information_catalog(),
            self._information_relations(),
            query,
        )
        return "ok", {"result": result.as_dict()}

    def _search_semantic(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"query", "endpoint", "retention_assumptions"},
        )
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        query = parse_semantic_query(
            _object_argument(request.arguments, "query")
        )
        provider_request = create_semantic_provider_request(
            query,
            endpoint=_string_argument(request.arguments, "endpoint"),
            retention_assumptions=_string_argument(
                request.arguments,
                "retention_assumptions",
            ),
        )
        approval = None
        if request.approval_id is not None:
            approval = ProviderApproval(
                request_id=provider_request.request_id,
                session_id=query.session_id,
                approval_id=request.approval_id,
                approved=True,
            )
        result = retrieve_semantic(
            self._information_catalog(),
            query,
            load_provider_gate_policy(self._repo_root),
            provider_request,
            approval=approval,
            remote_scorer=self._semantic_remote_scorers.get(query.provider),
        )
        return "ok", {"result": result.as_dict()}

    def _index_hybrid(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set())
        catalog = self._information_catalog()
        plan = prepare_hybrid_index(
            self._store.data_root,
            catalog,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact plan id returned by a prior dry-run"
            )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        result = apply_hybrid_index(
            self._store.data_root,
            catalog,
            plan,
            authorization,
        )
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
        }

    def _search_hybrid(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"query"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        query = parse_hybrid_query(_object_argument(request.arguments, "query"))
        result = retrieve_hybrid(
            self._store.data_root,
            self._information_catalog(),
            self._information_relations(),
            query,
        )
        return "ok", {"result": result.as_dict()}

    def _context_entries(self, catalog: InformationCatalog) -> dict[str, CatalogEntry]:
        entries = {entry.record.record_id: entry for entry in catalog.entries}
        current_revisions = catalog.current_source_revisions()
        for stored in self._store.list_records("memory"):
            record = parse_information_record(dict(stored.payload))
            if record.record_id in entries:
                raise ApplicationServiceError("context record ids must be unique")
            if record.lifecycle in {"superseded", "archived"}:
                availability = record.lifecycle
            elif record.lifecycle == "stale" or record_is_stale(
                record,
                current_revisions,
            ):
                availability = "stale"
            else:
                availability = "current"
            entries[record.record_id] = CatalogEntry(
                record=record,
                availability=availability,
                binding_ref=None,
            )
        return entries

    def _build_context(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"request", "candidates"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        build_request = parse_context_build_request(
            _object_argument(request.arguments, "request")
        )
        candidate_payloads = request.arguments.get("candidates")
        if not isinstance(candidate_payloads, list) or not candidate_payloads:
            raise ApplicationServiceError("candidates must be a non-empty list")
        entries = self._context_entries(self._information_catalog())
        candidates = []
        expected_fields = {
            "record_id",
            "layer",
            "selection_source",
            "selection_reason",
            "required",
            "priority",
            "allow_truncation",
        }
        for payload in candidate_payloads:
            if not isinstance(payload, dict) or set(payload) != expected_fields:
                raise ApplicationServiceError("context candidate fields are invalid")
            record_id = _identifier_argument(payload, "record_id")
            entry = entries.get(record_id)
            if entry is None:
                raise ApplicationServiceError("context candidate was not found")
            candidates.append(
                context_candidate_from_entry(
                    entry,
                    layer=_string_argument(payload, "layer"),
                    selection_source=_string_argument(payload, "selection_source"),
                    selection_reason=_string_argument(payload, "selection_reason"),
                    required=payload.get("required"),
                    priority=payload.get("priority"),
                    allow_truncation=payload.get("allow_truncation"),
                )
            )
        package = build_context_package(build_request, candidates)
        return "ok", {"context": package.as_dict()}

    def _propose_memory(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"candidate"})
        if request.apply:
            raise ApplicationServiceError("review operation cannot be applied")
        candidate = parse_memory_candidate(
            _object_argument(request.arguments, "candidate")
        )
        return "ok", {"candidate": candidate.as_payload(), "persisted": False}

    def _review_memory(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"candidate", "review"})
        if request.apply:
            raise ApplicationServiceError("review operation cannot be applied")
        candidate = parse_memory_candidate(
            _object_argument(request.arguments, "candidate")
        )
        review = parse_memory_review(_object_argument(request.arguments, "review"))
        if (
            review.candidate_id != candidate.candidate_id
            or review.candidate_digest != candidate.candidate_digest
        ):
            raise ApplicationServiceError("memory review does not match the candidate")
        persistence_eligible = False
        if review.outcome == "approved":
            stored = self._store.read(
                "memory",
                candidate.proposed_memory.record_id,
            )
            expected_revision = stored.revision if stored is not None else 0
            prepare_memory_persistence(
                self._store,
                candidate,
                review,
                expected_revision=expected_revision,
            )
            persistence_eligible = True
        return "ok", {
            "review": review.as_payload(),
            "persistence_eligible": persistence_eligible,
            "persisted": False,
        }

    def _persist_memory(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"candidate", "review", "expected_revision"},
        )
        candidate = parse_memory_candidate(
            _object_argument(request.arguments, "candidate")
        )
        review = parse_memory_review(_object_argument(request.arguments, "review"))
        plan = prepare_memory_persistence(
            self._store,
            candidate,
            review,
            expected_revision=_nonnegative_integer_argument(
                request.arguments,
                "expected_revision",
            ),
        )
        plan_summary = {
            "plan_id": plan.write_plan.mutation.plan_id,
            **plan.public_summary(),
        }
        if not request.apply:
            return "planned", {"plan": plan_summary, "applied": False}
        if request.approval_id != review.approval_id:
            raise ApplicationServiceError(
                "memory mutation approval must match the approved review"
            )
        authorization = self._authorize_record_plans(
            request,
            plan.write_plan.mutation.plan_id,
            (plan.write_plan,),
        )[plan.write_plan.mutation.plan_id]
        stored = apply_memory_persistence(
            self._store,
            plan,
            candidate,
            review,
            authorization,
        )
        return "applied", {
            "plan": plan_summary,
            "record": stored.public_summary(),
            "applied": True,
        }

    def _change_memory_lifecycle(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"action"})
        action = parse_memory_action(_object_argument(request.arguments, "action"))
        plan = prepare_memory_lifecycle(self._store, action)
        plan_summary = {
            "plan_id": plan.write_plan.mutation.plan_id,
            "action_digest": plan.action_digest,
            "memory": plan.memory_record.public_summary(),
            "write": plan.write_plan.public_summary(),
        }
        if not request.apply:
            return "planned", {"plan": plan_summary, "applied": False}
        if request.approval_id != action.approval_id:
            raise ApplicationServiceError(
                "memory mutation approval must match the approved action"
            )
        authorization = self._authorize_record_plans(
            request,
            plan.write_plan.mutation.plan_id,
            (plan.write_plan,),
        )[plan.write_plan.mutation.plan_id]
        stored = apply_memory_lifecycle(
            self._store,
            plan,
            action,
            authorization,
        )
        return "applied", {
            "plan": plan_summary,
            "record": stored.public_summary(),
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


def create_application_service(
    repo_root: Path,
    data_root: Path | None = None,
    **options: object,
) -> KrcnApplicationService:
    """Create the shared service with the same portable user home for every client."""

    repository = repo_root.resolve()
    home = resolve_user_home(data_root).path
    store = LocalWorkspaceStore(
        home,
        OwnershipResolver.from_repository(repository),
    )
    if "sqlite_runtime" not in options:
        options["sqlite_runtime"] = SqliteReferenceRuntime(
            repository,
            home / "secrets",
        )
    return KrcnApplicationService(repository, store, **options)

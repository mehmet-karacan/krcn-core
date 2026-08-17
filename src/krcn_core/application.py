"""Transport-neutral application services shared by every KRCN client."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from .adapter_gate import (
    AdapterApproval,
    authorize_adapter_operation,
    prepare_adapter_operation,
)
from .agent_runtime import (
    AgentRuntimeQueue,
    apply_runtime_queue_action,
    load_scheduler_policy,
    prepare_runtime_queue_action,
)
from .discovery import (
    DiscoveryResult,
    LOCAL_DISCOVERY_ADAPTER,
    discover_local_source,
    load_discovery_policy,
)
from .deployment import authorize_deployment_plan, prepare_deployment_plan
from .database_policy import require_oracle_metadata_template
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
from .unified_retrieval import (
    INTENT_DOMAINS,
    batch_from_hybrid,
    batch_from_oracle,
    batch_from_source_code,
    batch_from_work_graph,
    create_unified_request,
    retrieve_unified,
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
from .client_capabilities import (
    ClientCapabilityProfile,
    create_client_capability_profile,
    load_client_capability_policy,
)
from .delegation_policy import (
    decide_delegation,
    load_delegation_policy,
    parse_delegation_decision,
)
from .adaptive_routing import (
    compare_shadow_route,
    decide_route,
    load_adaptive_routing_policy,
    parse_route_request,
)
from .adaptive_routing_store import (
    apply_route_decision_record,
    prepare_route_decision_record,
)
from .agent_result_normalizer import normalize_native_client_result
from .agent_result_fanin import build_agent_result_fan_in, build_execution_trace_from_results
from .execution_coordinator import prepare_execution_coordination
from .memory_gate import (
    apply_memory_lifecycle,
    apply_memory_persistence,
    parse_memory_action,
    parse_memory_candidate,
    parse_memory_review,
    prepare_memory_lifecycle,
    prepare_memory_persistence,
)
from .memory_hygiene import (
    build_context_effectiveness,
    build_memory_hygiene_report,
    load_memory_hygiene_policy,
    parse_context_effectiveness,
    parse_memory_metadata_overlay,
    parse_research_evidence_metadata,
)
from .measured_loop import (
    build_measured_loop_status,
    build_morning_digest,
    decide_admission,
    load_measured_loop_policy,
)
from .model_routing import load_model_routing_policy, resolve_model_route
from .model_benchmark import (
    apply_project_benchmark_suite,
    list_project_benchmark_suites,
    prepare_project_benchmark_suite,
)
from .model_benchmark_runner import (
    BenchmarkExecutionHost,
    build_execution_authorization_digest,
    execute_model_benchmark_run_from_store,
    prepare_model_benchmark_run_from_store,
    resolve_authoritative_benchmark_inputs,
    validate_benchmark_execution_host,
)
from .model_inventory import (
    apply_model_inventory,
    list_model_inventory,
    parse_model_inventory_record,
    prepare_model_inventory,
)
from .model_health import (
    ModelHealthProbe,
    list_model_health,
    load_model_health_policy,
    persist_model_health_observation,
    prepare_model_health_action,
)
from .model_decision import (
    decide_model_assignment_from_store,
    decide_task_plan_model_assignments_from_store,
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
from .orchestration_intent import parse_task_intent
from .orchestration_plan import parse_task_plan
from .orchestration_verifier import VerifierHandlerRegistry
from .orchestration_worker import WorkerHandlerRegistry
from .oracle_metadata import (
    OracleApplyAuthorization,
    OracleCollectionPolicy,
    OracleIndexAuthorization,
    OracleMetadataTransport,
    OracleReadAuthorization,
    apply_oracle_index,
    apply_oracle_plan,
    collect_oracle_snapshot,
    oracle_index_path,
    prepare_oracle_apply,
    prepare_oracle_index,
    retrieve_oracle_dependencies,
    search_oracle_metadata,
)
from .policies import load_user_policies
from .project_learning import apply_project_learning, prepare_project_learning
from .project_integration import (
    apply_project_integration,
    prepare_project_integration,
)
from .project_learning_intent import parse_project_learning_intent
from .project_context import (
    ProjectContextError,
    build_project_resume_summary,
    project_navigation_menu,
    project_work_list,
    resolve_current_project,
    suggest_projects,
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
from .project_capsule_migration import (
    apply_project_capsule_migration,
    prepare_project_capsule_migration,
)
from .project_capsule_portability import (
    apply_project_capsule_export,
    apply_project_capsule_import,
    prepare_project_capsule_export,
    prepare_project_capsule_import,
)
from .portable_backup import apply_portable_backup, prepare_portable_backup
from .portable_restore import apply_portable_restore, prepare_portable_restore
from .provider_gate import (
    ProviderApproval,
    authorize_provider_request,
    create_provider_request,
    load_provider_gate_policy,
)
from .outbound_assurance import (
    decide_outbound_data,
    load_outbound_assurance_policy,
    parse_provider_assurance_profile,
)
from .worktree_sandbox import (
    parse_sandbox_host_profile,
    prepare_worktree_sandbox,
)
from .implementation_delivery import (
    ImplementationDeliveryHost,
    apply_implementation_plan,
    parse_implementation_result,
    prepare_implementation_plan,
    verify_implementation_result,
)
from .route_enforcement import decide_route_enforcement, load_route_enforcement_policy
from .team_runtime_need import assess_team_runtime_need, load_team_runtime_need_policy
from .rescan import apply_rescan, prepare_rescan
from .research_orchestration import (
    apply_research_result_import,
    apply_research_run,
    get_research_status,
    prepare_research_result_import,
    prepare_research_run,
)
from .research_intent import ResearchIntentError, parse_research_intent
from .research_execution import (
    ExecutableResolver,
    ProcessRunner,
    ResearchExecutionPlan,
    load_research_execution_policy,
    probe_research_execution,
    resolve_research_execution,
)
from .research_runtime_adapter import (
    bind_research_runtime_adapter,
    create_research_runtime_adapter,
)
from .research_runtime import (
    RESEARCH_DAG,
    ResearchWorkUnit,
    dispatch_research_runtime,
    get_research_runtime_status,
    prepare_research_runtime_dispatch,
)
from .retrieval_quality import (
    build_retrieval_scale_manifest,
    evaluate_retrieval_golden_set,
    load_retrieval_golden_set,
    load_retrieval_scale_policy,
    parse_retrieval_observations,
)
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
from .source_code_index import (
    LOCAL_SOURCE_CODE_ADAPTER,
    apply_source_code_index,
    parse_source_code_query,
    prepare_source_code_index,
    retrieve_source_code,
    source_code_index_is_current,
    source_code_index_summary,
)
from .source_state import parse_source_state
from .skill_lifecycle import (
    build_skill_evaluation,
    load_skill_lifecycle_policy,
    parse_skill_candidate,
    parse_skill_evaluation,
    parse_skill_lifecycle_record,
    prepare_skill_activation,
    prepare_skill_state_change,
)
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
from .work_graph import (
    ACTIVE_STATUSES,
    apply_work_item,
    parse_work_item,
    prepare_work_item,
    query_work_graph,
    query_work_history,
)
from .work_import import (
    apply_work_import,
    inventory_work_source,
    parse_work_import_request,
    prepare_work_import,
)
from .work_index import apply_work_index, prepare_work_index
from .work_documents import (
    WorkDocumentError,
    apply_work_document_manifest_update,
    apply_initial_work_document_copy,
    prepare_initial_work_document_copy,
    prepare_work_document_manifest_update,
    prepare_work_document_processing,
)
from .work_document_layout_migration import (
    apply_work_document_layout_migration,
    prepare_work_document_layout_migration,
)
from .work_retrieval import search_work
from .work_semantic_index import (
    apply_work_semantic_index,
    prepare_work_semantic_index,
)
from .application_contract import (
    IDENTIFIER,
    OPERATIONS,
    ApplicationServiceError,
    ServiceRequest,
    ServiceResponse,
    check_arguments as _check_arguments,
    identifier_argument as _identifier_argument,
    nonnegative_integer_argument as _nonnegative_integer_argument,
    object_argument as _object_argument,
    reviewed_identity_decisions_argument as _reviewed_identity_decisions_argument,
    string_argument as _string_argument,
    string_tuple_argument as _string_tuple_argument,
    text_argument as _text_argument,
)
from .application_registry import bind_application_handlers


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
        oracle_metadata_transports: Mapping[str, OracleMetadataTransport] | None = None,
        model_health_probes: Mapping[str, ModelHealthProbe] | None = None,
        model_benchmark_hosts: Mapping[str, BenchmarkExecutionHost] | None = None,
        model_benchmark_adapters: Mapping[str, Callable[..., object]] | None = None,
        implementation_delivery_hosts: Mapping[str, ImplementationDeliveryHost] | None = None,
        research_execution_adapters: Mapping[
            str, Callable[[ResearchWorkUnit], Mapping[str, object]]
        ] | None = None,
        research_process_runners: Mapping[str, ProcessRunner] | None = None,
        research_executable_resolver: ExecutableResolver | None = None,
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
        transports = dict(oracle_metadata_transports or {})
        if any(
            not isinstance(integration_id, str)
            or not IDENTIFIER.fullmatch(integration_id)
            or any(
                not callable(getattr(transport, method, None))
                for method in (
                    "inventory",
                    "fetch_ddl_select",
                    "fetch_ddl_batch",
                    "fetch_structured_metadata",
                    "fetch_dependencies",
                )
            )
            for integration_id, transport in transports.items()
        ):
            raise ApplicationServiceError("Oracle metadata transports are invalid")
        self._oracle_metadata_transports = transports
        health_probes = dict(model_health_probes or {})
        if any(
            not isinstance(provider_ref, str)
            or not IDENTIFIER.fullmatch(provider_ref)
            or not callable(getattr(probe, "probe", None))
            for provider_ref, probe in health_probes.items()
        ):
            raise ApplicationServiceError("model health probes are invalid")
        self._model_health_probes = health_probes
        if model_benchmark_adapters:
            raise ApplicationServiceError(
                "plain model benchmark adapters are replay-unsafe and unsupported"
            )
        benchmark_hosts = dict(model_benchmark_hosts or {})
        try:
            for model_ref, host in benchmark_hosts.items():
                if not isinstance(model_ref, str) or not IDENTIFIER.fullmatch(model_ref):
                    raise ApplicationServiceError(
                        "model benchmark host identity is invalid"
                    )
                validate_benchmark_execution_host(host, model_ref=model_ref)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        self._model_benchmark_hosts = benchmark_hosts
        delivery_hosts = dict(implementation_delivery_hosts or {})
        if any(
            not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id)
            or any(not callable(getattr(host, method, None)) for method in ("report_bytes", "patch_artifact", "test_runner"))
            for project_id, host in delivery_hosts.items()
        ):
            raise ApplicationServiceError("implementation delivery hosts are invalid")
        self._implementation_delivery_hosts = delivery_hosts
        research_adapters = dict(research_execution_adapters or {})
        if research_adapters and (
            set(research_adapters) != set(RESEARCH_DAG)
            or any(not callable(adapter) for adapter in research_adapters.values())
        ):
            raise ApplicationServiceError(
                "research execution adapters must cover every runtime role"
            )
        self._research_execution_adapters = research_adapters
        runners = dict(research_process_runners or {})
        if set(runners) - set(RESEARCH_DAG) or any(
            not callable(getattr(runner, "run", None)) for runner in runners.values()
        ):
            raise ApplicationServiceError("research process runners are invalid")
        if research_executable_resolver is not None and not callable(research_executable_resolver):
            raise ApplicationServiceError("research executable resolver is invalid")
        self._research_process_runners = runners
        self._research_executable_resolver = research_executable_resolver
        self._research_cancellations: dict[tuple[str, str], threading.Event] = {}
        self._research_cancellation_lock = threading.Lock()
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
        handlers = bind_application_handlers(self)
        status, data = handlers[request.operation](request)
        return ServiceResponse(
            request_id=request.request_id,
            operation=request.operation,
            status=status,
            data=data,
        )

    def _coordinate_execution(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError(
                "execution coordination preparation is read-only"
            )
        required = {
            "request_id",
            "client_id",
            "request_text",
            "work_class",
            "intent",
            "context_digest",
            "delegation",
        }
        optional = {
            "project_id",
            "work_item_id",
            "work_item_revision",
            "work_item_digest",
            "task_plan",
            "task_authorization_id",
            "model_assignment_ids",
            "dag_execution_plan_id",
            "route_request",
        }
        if set(request.arguments) - required - optional or not required.issubset(
            request.arguments
        ):
            raise ApplicationServiceError(
                "execution coordination arguments are invalid"
            )
        try:
            intent = parse_task_intent(request.arguments["intent"])
            delegation = parse_delegation_decision(
                request.arguments["delegation"]
            )
            task_plan_payload = request.arguments.get("task_plan")
            task_plan = (
                parse_task_plan(task_plan_payload)
                if task_plan_payload is not None
                else None
            )
            model_assignments = request.arguments.get(
                "model_assignment_ids",
                [],
            )
            if not isinstance(model_assignments, list):
                raise ValueError("model assignment ids must be a list")
            route_request_payload = request.arguments.get("route_request")
            adaptive_routing_policy = None
            route_request = None
            if route_request_payload is not None:
                adaptive_routing_policy = load_adaptive_routing_policy(
                    self._repo_root
                )
                route_request = parse_route_request(
                    route_request_payload, adaptive_routing_policy
                )
            plan = prepare_execution_coordination(
                request_id=request.arguments["request_id"],
                client_id=request.arguments["client_id"],
                request_text=request.arguments["request_text"],
                work_class=request.arguments["work_class"],
                intent=intent,
                context_digest=request.arguments["context_digest"],
                delegation=delegation,
                project_id=request.arguments.get("project_id"),
                work_item_id=request.arguments.get("work_item_id"),
                work_item_revision=request.arguments.get("work_item_revision"),
                work_item_digest=request.arguments.get("work_item_digest"),
                task_plan=task_plan,
                task_authorization_id=request.arguments.get(
                    "task_authorization_id"
                ),
                model_assignment_ids=model_assignments,
                dag_execution_plan_id=request.arguments.get(
                    "dag_execution_plan_id"
                ),
                route_request=route_request,
                adaptive_routing_policy=adaptive_routing_policy,
            )
        except ValueError as exc:
            raise ApplicationServiceError(
                "execution coordination request is invalid"
            ) from exc
        data = {"coordination_plan": plan.as_dict()}
        return (
            "blocked" if plan.as_dict()["status"] == "blocked" else "planned",
            data,
        )

    def _routing_decide(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"route_request"})
        if request.apply:
            raise ApplicationServiceError("adaptive routing decision is read-only")
        try:
            policy = load_adaptive_routing_policy(self._repo_root)
            route_request = parse_route_request(
                _object_argument(request.arguments, "route_request"), policy
            )
            decision = decide_route(policy, route_request)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "decision": decision.as_dict(),
            "shadow_only": True,
            "behavior_changed": False,
            "persisted": False,
            "grants_authority": False,
        }

    def _outbound_assess(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"provider_request", "payload_digest", "data_categories", "evaluated_at"},
            optional={"provider_approval", "assurance_profile"},
        )
        if request.apply:
            raise ApplicationServiceError("outbound assessment is read-only")
        try:
            raw = _object_argument(request.arguments, "provider_request")
            expected = {
                "schema_version", "request_id", "provider", "endpoint",
                "data_categories", "operation_scope", "retention_assumptions",
                "session_id", "remote",
            }
            if set(raw) != expected or raw["schema_version"] != 1:
                raise ValueError("provider request fields are invalid")
            categories = raw["data_categories"]
            if not isinstance(categories, list):
                raise ValueError("provider request categories are invalid")
            provider_request = create_provider_request(
                provider=str(raw["provider"]), endpoint=str(raw["endpoint"]),
                data_categories=tuple(str(item) for item in categories),
                operation_scope=str(raw["operation_scope"]),
                retention_assumptions=str(raw["retention_assumptions"]),
                session_id=str(raw["session_id"]), remote=raw["remote"],
            )
            if raw["request_id"] != provider_request.request_id:
                raise ValueError("provider request digest is invalid")
            approval_payload = request.arguments.get("provider_approval")
            approval = None
            if approval_payload is not None:
                if not isinstance(approval_payload, Mapping) or set(approval_payload) != {"request_id", "session_id", "approval_id", "approved"}:
                    raise ValueError("provider approval fields are invalid")
                approval = ProviderApproval(
                    str(approval_payload["request_id"]), str(approval_payload["session_id"]),
                    str(approval_payload["approval_id"]), approval_payload["approved"],
                )
            authorization = authorize_provider_request(
                load_provider_gate_policy(self._repo_root), provider_request, approval=approval
            )
            profile_payload = request.arguments.get("assurance_profile")
            profile = parse_provider_assurance_profile(profile_payload) if profile_payload is not None else None
            decision = decide_outbound_data(
                load_outbound_assurance_policy(self._repo_root), authorization,
                payload_digest=_string_argument(request.arguments, "payload_digest"),
                data_categories=_string_tuple_argument(request.arguments, "data_categories"),
                evaluated_at=_string_argument(request.arguments, "evaluated_at"),
                assurance=profile,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return ("ok" if decision.verdict != "blocked" else "blocked"), {
            "decision": decision.as_dict(),
            "provider_authorization_verified": authorization.approval_verified,
            "payload_disclosed": False,
            "authority_granted": False,
        }

    def _sandbox_plan(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "source_root", "project_id", "task_plan_id", "worker_step_id",
                "validation_gate_id", "effect_claim_id", "allowed_paths",
                "allowed_executables", "allowed_env_keys", "host_profile",
            },
            optional={"network_authorization_digest", "maximum_patch_bytes"},
        )
        if request.apply:
            raise ApplicationServiceError("sandbox planning is read-only")
        source_root = Path(_string_argument(request.arguments, "source_root"))
        if not source_root.is_absolute():
            raise ApplicationServiceError("sandbox source root must be absolute")
        maximum = request.arguments.get("maximum_patch_bytes", 8388608)
        if isinstance(maximum, bool) or not isinstance(maximum, int):
            raise ApplicationServiceError("maximum_patch_bytes must be an integer")
        try:
            host = parse_sandbox_host_profile(_object_argument(request.arguments, "host_profile"))
            plan = prepare_worktree_sandbox(
                source_root.resolve(), self._ownership,
                project_id=_identifier_argument(request.arguments, "project_id"),
                task_plan_id=_string_argument(request.arguments, "task_plan_id"),
                worker_step_id=_identifier_argument(request.arguments, "worker_step_id"),
                validation_gate_id=_string_argument(request.arguments, "validation_gate_id"),
                effect_claim_id=_string_argument(request.arguments, "effect_claim_id"),
                allowed_paths=_string_tuple_argument(request.arguments, "allowed_paths"),
                allowed_executables=_string_tuple_argument(request.arguments, "allowed_executables"),
                allowed_env_keys=_string_tuple_argument(request.arguments, "allowed_env_keys"),
                host_profile=host,
                network_authorization_digest=request.arguments.get("network_authorization_digest"),
                maximum_patch_bytes=maximum,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return ("planned" if plan.payload["execution_allowed"] else "blocked"), {
            "plan": plan.as_dict(),
            "mutation_plan": plan.mutation_plan.as_dict(),
            "expected_plan_id": plan.plan_id,
            "source_path_disclosed": False,
            "apply_supported": False,
            "authority_granted": False,
        }

    def _implementation_plan_from_request(self, request: ServiceRequest):
        required = {"project_id", "work_item_id", "task_plan_id", "report_ref", "artifact_id", "test_specs", "execution_trace_ref"}
        _check_arguments(request.arguments, required=required, optional={"result", "verifier_identity_digest", "verifier_evidence_digest"})
        project_id = _identifier_argument(request.arguments, "project_id")
        host = self._implementation_delivery_hosts.get(project_id)
        if host is None:
            raise ApplicationServiceError("implementation delivery host is unavailable")
        report_ref = _string_argument(request.arguments, "report_ref")
        artifact_id = _string_argument(request.arguments, "artifact_id")
        specs = request.arguments["test_specs"]
        if not isinstance(specs, list):
            raise ApplicationServiceError("test_specs must be a list")
        try:
            artifact = host.patch_artifact(artifact_id)
            report = host.report_bytes(report_ref)
            plan = prepare_implementation_plan(
                self._repo_root, self._ownership, project_id=project_id,
                work_item_id=_identifier_argument(request.arguments, "work_item_id"),
                task_plan_id=_string_argument(request.arguments, "task_plan_id"), report_ref=report_ref,
                report_bytes=report, artifact=artifact, test_specs=specs,
                execution_trace_ref=_string_argument(request.arguments, "execution_trace_ref"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return host, report, artifact, plan

    def _implementation_action(self, request: ServiceRequest) -> tuple[str, Mapping[str, object]]:
        host, report, artifact, plan = self._implementation_plan_from_request(request)
        if request.operation in {"implementation.plan", "implementation.show", "implementation.status"}:
            if request.apply:
                raise ApplicationServiceError("implementation inspection is read-only")
            return "planned", {"plan": plan.as_dict(), "mutation_plans": [item.as_dict() for item in plan.mutation_plans], "apply_supported": True, "authority_granted": False}
        if request.operation == "implementation.verify":
            if request.apply:
                raise ApplicationServiceError("implementation verification records evidence but grants no mutation authority")
            try:
                result = parse_implementation_result(_object_argument(request.arguments, "result"))
                verification = verify_implementation_result(
                    plan, result,
                    verifier_identity_digest=_string_argument(request.arguments, "verifier_identity_digest"),
                    verifier_evidence_digest=_string_argument(request.arguments, "verifier_evidence_digest"),
                )
            except ValueError as exc:
                raise ApplicationServiceError(str(exc)) from exc
            return "ok", {"verification": verification.as_dict(), "authority_granted": False}
        if not request.apply:
            return "planned", {"plan": plan.as_dict(), "mutation_plans": [item.as_dict() for item in plan.mutation_plans], "applied": False, "authority_granted": False}
        authorizations = self._authorize_effect_plans(request, plan.plan_id, plan.mutation_plans, "implementation delivery")
        try:
            result = apply_implementation_plan(plan, artifact, authorizations, expected_plan_id=request.expected_plan_id or "", current_report_bytes=report, test_runner=host.test_runner())
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {"plan": plan.as_dict(), "result": result.as_dict(), "applied": True, "authority_granted": False}

    def _route_enforcement(self, request: ServiceRequest) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"current_stage", "requested_stage", "observation_count", "mismatch_count", "project_opt_in"})
        if request.apply:
            raise ApplicationServiceError("route enforcement decision is read-only")
        try:
            decision = decide_route_enforcement(
                load_route_enforcement_policy(self._repo_root),
                current_stage=_string_argument(request.arguments, "current_stage"), requested_stage=_string_argument(request.arguments, "requested_stage"),
                observation_count=_nonnegative_integer_argument(request.arguments, "observation_count"), mismatch_count=_nonnegative_integer_argument(request.arguments, "mismatch_count"),
                project_opt_in=request.arguments["project_opt_in"],
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return ("ok" if decision.payload["allowed"] else "blocked"), {"decision": decision.as_dict(), "authority_granted": False}

    def _team_runtime_assess(self, request: ServiceRequest) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"machine_count", "concurrent_worker_count", "cross_machine_claim_required", "enterprise_needs", "migration_owner_assigned", "rollback_owner_assigned", "operating_budget_approved"})
        if request.apply:
            raise ApplicationServiceError("team runtime need assessment is read-only")
        needs = request.arguments["enterprise_needs"]
        if not isinstance(needs, list):
            raise ApplicationServiceError("enterprise_needs must be a list")
        try:
            assessment = assess_team_runtime_need(
                load_team_runtime_need_policy(self._repo_root),
                machine_count=_nonnegative_integer_argument(request.arguments, "machine_count"), concurrent_worker_count=_nonnegative_integer_argument(request.arguments, "concurrent_worker_count"),
                cross_machine_claim_required=request.arguments["cross_machine_claim_required"], enterprise_needs=tuple(needs),
                migration_owner_assigned=request.arguments["migration_owner_assigned"], rollback_owner_assigned=request.arguments["rollback_owner_assigned"], operating_budget_approved=request.arguments["operating_budget_approved"],
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"assessment": assessment.as_dict(), "next_stage": "separate-team-runtime-plan" if assessment.payload["decision"] == "eligible-for-separate-plan" else "keep-local-first", "authority_granted": False}

    def _routing_explain(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"route_request", "observed_route"},
        )
        if request.apply:
            raise ApplicationServiceError("adaptive routing explanation is read-only")
        try:
            policy = load_adaptive_routing_policy(self._repo_root)
            route_request = parse_route_request(
                _object_argument(request.arguments, "route_request"), policy
            )
            decision = decide_route(policy, route_request)
            comparison = compare_shadow_route(
                policy,
                decision,
                observed_route=_string_argument(
                    request.arguments, "observed_route"
                ),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "decision": decision.as_dict(),
            "comparison": comparison.as_dict(),
            "shadow_only": True,
            "behavior_changed": False,
            "persisted": False,
            "grants_authority": False,
        }

    def _routing_record(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"route_request", "recorded_at"},
        )
        try:
            policy = load_adaptive_routing_policy(self._repo_root)
            route_request = parse_route_request(
                _object_argument(request.arguments, "route_request"), policy
            )
            decision = decide_route(policy, route_request)
            plan = prepare_route_decision_record(
                self._store,
                policy,
                decision,
                recorded_at=_string_argument(request.arguments, "recorded_at"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        if not request.apply:
            return "current" if plan.no_op else "planned", {
                "decision": decision.as_dict(),
                "plan": plan.public_summary(),
                "persisted": plan.no_op,
                "grants_authority": False,
            }
        record_plans = () if plan.write_plan is None else (plan.write_plan,)
        authorizations = self._authorize_record_plans(
            request,
            plan.plan_id,
            record_plans,
        )
        result = apply_route_decision_record(
            self._store,
            policy,
            plan,
            authorizations,
            expected_plan_id=request.expected_plan_id or "",
        )
        return "current" if result["no_op"] else "applied", {
            "decision": decision.as_dict(),
            "plan": plan.public_summary(),
            "result": result,
            "persisted": True,
            "grants_authority": False,
        }

    def _normalize_native_result(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"native_result", "context"})
        if request.apply:
            raise ApplicationServiceError("agent result normalization is read-only")
        try:
            normalized = normalize_native_client_result(
                _object_argument(request.arguments, "native_result"),
                _object_argument(request.arguments, "context"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"normalized_result": normalized.as_dict(), "grants_authority": False}

    def _fan_in_agent_results(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"normalized_results", "expected_step_ids", "coordinator_execution_identity_id", "caller_role"},
        )
        if request.apply:
            raise ApplicationServiceError("agent result fan-in is read-only")
        results = request.arguments.get("normalized_results")
        if not isinstance(results, list):
            raise ApplicationServiceError("normalized_results must be a list")
        try:
            fan_in = build_agent_result_fan_in(
                results,
                expected_step_ids=_string_tuple_argument(request.arguments, "expected_step_ids"),
                coordinator_execution_identity_id=_string_argument(request.arguments, "coordinator_execution_identity_id"),
                caller_role=_string_argument(request.arguments, "caller_role"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"fan_in": fan_in.as_dict(), "grants_authority": False}

    def _trace_agent_results(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        required = {"normalized_results", "request_id", "client_id", "intent_digest", "context_digest", "delegation_mode"}
        _check_arguments(request.arguments, required=required, optional={"approval_envelope_id"})
        if request.apply:
            raise ApplicationServiceError("agent result trace aggregation is read-only")
        results = request.arguments.get("normalized_results")
        if not isinstance(results, list):
            raise ApplicationServiceError("normalized_results must be a list")
        approval = request.arguments.get("approval_envelope_id")
        if approval is not None and not isinstance(approval, str):
            raise ApplicationServiceError("approval_envelope_id must be text or null")
        try:
            trace = build_execution_trace_from_results(
                results,
                request_id=_string_argument(request.arguments, "request_id"),
                client_id=_string_argument(request.arguments, "client_id"),
                intent_digest=_string_argument(request.arguments, "intent_digest"),
                context_digest=_string_argument(request.arguments, "context_digest"),
                delegation_mode=_string_argument(request.arguments, "delegation_mode"),
                approval_envelope_id=approval,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"execution_trace": trace.as_dict(), "grants_authority": False}

    def _put_work_item(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        plan = prepare_work_item(
            self._store,
            self._ownership,
            request.arguments,
            repo_root=self._repo_root,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "work item update",
        )
        result = apply_work_item(self._store, plan, authorizations)
        return "applied", {"plan": plan.public_summary(), "result": result, "applied": True}

    def _import_work(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"source_root", "import_request"},
        )
        source_root = Path(_string_argument(request.arguments, "source_root"))
        if not source_root.is_absolute():
            raise ApplicationServiceError("source_root must be absolute")
        import_request = _object_argument(request.arguments, "import_request")
        _, declared_inventory, _ = parse_work_import_request(import_request)
        current_inventory = inventory_work_source(
            source_root,
            source_id=declared_inventory.source_id,
            logical_root=declared_inventory.logical_root,
        )
        if current_inventory.inventory_digest != declared_inventory.inventory_digest:
            raise ApplicationServiceError(
                "work import source inventory does not match the physical source"
            )
        plan = prepare_work_import(
            self._store,
            self._ownership,
            import_request,
            repo_root=self._repo_root,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact work import plan id"
            )
        if plan.no_op:
            authorizations: dict[str, MutationAuthorization] = {}
        else:
            authorizations = self._authorize_effect_plans(
                request,
                plan.plan_id,
                plan.effect_plans,
                "work import",
            )
        refreshed_inventory = inventory_work_source(
            source_root,
            source_id=declared_inventory.source_id,
            logical_root=declared_inventory.logical_root,
        )
        result = apply_work_import(
            self._store,
            plan,
            authorizations,
            expected_plan_id=plan.plan_id,
            current_source_inventory=refreshed_inventory.as_dict(),
        )
        return "applied", {
            "plan": plan.public_summary(),
            "result": result.as_dict(),
            "applied": True,
        }

    def _index_work_semantic(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        project_id = _identifier_argument(request.arguments, "project_id")
        plan = prepare_work_semantic_index(
            self._repo_root,
            self._store,
            self._ownership,
            project_id,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact work semantic index plan id"
            )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        result = apply_work_semantic_index(
            self._repo_root,
            self._store,
            plan,
            authorization,
        )
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
        }

    def _index_work_readable(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        project_id = _identifier_argument(request.arguments, "project_id")
        if self._store.read("projects", project_id) is None:
            raise ApplicationServiceError("readable work index project is not registered")
        plan = prepare_work_index(
            self._repo_root,
            self._store,
            self._ownership,
            project_id,
        )
        if not request.apply:
            return (
                "ok" if plan.no_op else "planned",
                {"plan": plan.public_summary(), "applied": False},
            )
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact readable work index plan id"
            )
        authorization = (
            None
            if plan.mutation is None
            else authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            )
        )
        result = apply_work_index(
            self._repo_root,
            self._store,
            self._ownership,
            plan,
            authorization,
            expected_plan_id=plan.plan_id,
        )
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
        }

    def _copy_initial_work_documents(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id", "db_scripts_root", "legacy_root"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        db_scripts_root = self._absolute_path_argument(request.arguments, "db_scripts_root")
        legacy_root = self._absolute_path_argument(request.arguments, "legacy_root")
        plan = prepare_initial_work_document_copy(
            self._store,
            self._ownership,
            project_id,
            db_scripts_root,
            legacy_root,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = (
            {}
            if plan.no_op
            else self._authorize_effect_plans(
                request,
                plan.plan_id,
                plan.effect_plans,
                "work document copy",
            )
        )
        result = apply_initial_work_document_copy(
            plan,
            authorizations,
            expected_plan_id=request.expected_plan_id or "",
        )
        return "applied", {"plan": plan.public_summary(), "result": result, "applied": True}

    def _migrate_work_document_layout(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id"},
            optional={"reviewed_identity_decisions"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        identity_decisions = _reviewed_identity_decisions_argument(
            request.arguments
        )
        plan = prepare_work_document_layout_migration(
            self._store,
            self._ownership,
            project_id,
            reviewed_identity_decisions=identity_decisions,
        )
        plan_summary = plan.public_summary()
        unresolved_count = int(plan_summary.get("unresolved_review_count", 0))
        excluded_count = int(plan_summary.get("excluded_count", 0))
        processing_required = bool(
            plan_summary.get("work_document_processing_required", False)
        )
        planned_next_actions: list[str] = []
        if unresolved_count:
            planned_next_actions.append(
                "Çözümlenmemiş kimlikleri request veya exclude olarak incele."
            )
        elif excluded_count:
            planned_next_actions.append(
                "Hariç bırakılan kimlik kararlarını gözden geçir; bu kayıtlar korunur."
            )
        if not plan.no_op and not unresolved_count:
            planned_next_actions.append(
                "Bu yerleşim migration exact planını kullanıcı onayıyla uygula."
            )
        if processing_required and not unresolved_count:
            planned_next_actions.extend([
                "work.documents.process için ayrı exact plan hazırla.",
                "Onaylı Work Graph güncellemesini ve derived rebuild işlemini uygula.",
            ])
        if not request.apply:
            return "planned", {
                "plan": plan_summary,
                "next_operation": (
                    "work.documents.process"
                    if processing_required and not unresolved_count
                    else None
                ),
                "next_actions": planned_next_actions,
                "applied": False,
            }
        if int(plan_summary.get("unresolved_review_count", 0)) > 0:
            raise ApplicationServiceError(
                "work document layout migration requires a reviewed identity mapping"
            )
        authorizations = (
            {}
            if plan.no_op
            else self._authorize_effect_plans(
                request,
                plan.plan_id,
                plan.effect_plans,
                "work document layout migration",
            )
        )
        result = apply_work_document_layout_migration(
            plan,
            authorizations,
            expected_plan_id=request.expected_plan_id or "",
        )
        return "applied", {
            "plan": plan_summary,
            "result": result,
            "next_operation": (
                "work.documents.process" if processing_required else None
            ),
            "next_actions": (
                (
                    [
                        "Hariç bırakılan kimlik kararlarını gözden geçir; bu kayıtlar korunur."
                    ]
                    if excluded_count
                    else []
                )
                + (
                    [
                        "work.documents.process için ayrı exact plan hazırla.",
                        "Onaylı Work Graph güncellemesini ve derived rebuild işlemini uygula.",
                    ]
                    if processing_required
                    else []
                )
            ),
            "applied": True,
        }

    def _process_work_documents(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id"},
            optional={"requested_external_id", "requested_work_type"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        requested_external_id = None
        if "requested_external_id" in request.arguments:
            requested_external_id = _string_argument(
                request.arguments, "requested_external_id"
            )
            if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", requested_external_id
            ):
                raise ApplicationServiceError(
                    "requested_external_id must be a portable external identity"
                )
        requested_work_type = None
        if "requested_work_type" in request.arguments:
            requested_work_type = _string_argument(
                request.arguments, "requested_work_type"
            )
            if requested_work_type not in {"request", "defect", "task"}:
                raise ApplicationServiceError(
                    "requested_work_type must be request, defect, or task"
                )
        manifest_plan = None
        if requested_work_type != "task":
            try:
                manifest_plan = prepare_work_document_manifest_update(
                    self._store,
                    self._ownership,
                    project_id,
                    requested_external_id=requested_external_id,
                    requested_work_type=requested_work_type,
                )
            except WorkDocumentError as exc:
                if str(exc) != "work document layout V2 migration is required":
                    raise
        if manifest_plan is not None and not manifest_plan.no_op:
            plan_summary: Mapping[str, object] = {
                "plan_id": manifest_plan.plan_id,
                "project_id": project_id,
                "requested_external_id": requested_external_id,
                "requested_work_type": requested_work_type,
                "manifest_update_required": True,
                "work_import_required": False,
                "manifest_update": manifest_plan.public_summary(),
            }
            next_actions = [
                "Yeni veya değişmiş V2 belgelerini manifest envanterine işleyen exact planı onayla.",
                "Manifest güncellemesinden sonra work.documents.process işlemini yeniden çalıştır.",
            ]
            if not request.apply:
                return "planned", {
                    "plan": plan_summary,
                    "next_operation": "work.documents.process",
                    "next_actions": next_actions,
                    "applied": False,
                }
            authorizations = self._authorize_effect_plans(
                request,
                manifest_plan.plan_id,
                manifest_plan.effect_plans,
                "work document manifest update",
            )
            authorization = (
                None
                if manifest_plan.mutation is None
                else authorizations[manifest_plan.mutation.plan_id]
            )
            manifest_result = apply_work_document_manifest_update(
                manifest_plan,
                authorization,
                expected_plan_id=request.expected_plan_id or "",
            )
            return "applied", {
                "plan": plan_summary,
                "manifest_update": manifest_result,
                "next_operation": "work.documents.process",
                "next_actions": [
                    "work.documents.process için yeni exact plan hazırla.",
                ],
                "applied": True,
            }
        import_plan, document_summary = prepare_work_document_processing(
            self._store,
            self._ownership,
            project_id,
            requested_external_id=requested_external_id,
            requested_work_type=requested_work_type,
            repo_root=self._repo_root,
        )
        if import_plan is None:
            semantic_plan = prepare_work_semantic_index(
                self._repo_root, self._store, self._ownership, project_id,
            )
            plan_id = semantic_plan.plan_id
            plan_summary: Mapping[str, object] = {
                "plan_id": plan_id,
                "project_id": project_id,
                "work_import_required": False,
                "semantic_index": semantic_plan.public_summary(),
                **document_summary,
            }
            if not request.apply:
                return "planned", {"plan": plan_summary, "applied": False}
            if request.expected_plan_id != plan_id:
                raise ApplicationServiceError(
                    "apply requires the exact work document processing plan id"
                )
            semantic_authorization = authorize_mutation(
                semantic_plan.mutation,
                dry_run=DryRunEvidence(semantic_plan.plan_id, verified=True),
            )
            semantic_result = apply_work_semantic_index(
                self._repo_root, self._store, semantic_plan, semantic_authorization,
            )
            return "applied", {
                "plan": plan_summary,
                "work_import": {"status": "current"},
                "semantic_index": semantic_result,
                "applied": True,
            }
        plan_summary = {
            "plan_id": import_plan.plan_id,
            "project_id": project_id,
            "work_import_required": True,
            "work_import": import_plan.public_summary(),
            **document_summary,
        }
        if not request.apply:
            return "planned", {"plan": plan_summary, "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            import_plan.plan_id,
            import_plan.effect_plans,
            "work document processing",
        )
        import_result = apply_work_import(
            self._store,
            import_plan,
            authorizations,
            expected_plan_id=import_plan.plan_id,
            current_source_inventory=import_plan.source_inventory.as_dict(),
        )
        semantic_plan = prepare_work_semantic_index(
            self._repo_root, self._store, self._ownership, project_id,
        )
        semantic_authorization = authorize_mutation(
            semantic_plan.mutation,
            dry_run=DryRunEvidence(semantic_plan.plan_id, verified=True),
        )
        semantic_result = apply_work_semantic_index(
            self._repo_root, self._store, semantic_plan, semantic_authorization,
        )
        return "applied", {
            "plan": plan_summary,
            "work_import": import_result.as_dict(),
            "semantic_index": semantic_result,
            "applied": True,
        }

    def _search_work(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError("work search is read-only")
        return "ok", {
            "result": search_work(
                self._repo_root,
                self._store,
                request.arguments,
            )
        }

    def _query_work(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError("work query cannot be applied")
        return "ok", {"result": query_work_graph(self._store, request.arguments)}

    def _work_history(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError("work history cannot be applied")
        return "ok", {"result": query_work_history(self._store, request.arguments)}

    def _prepare_research(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        try:
            plan = prepare_research_run(
                self._repo_root,
                self._store,
                self._ownership,
                request.arguments,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        if not request.apply:
            return "planned", {
                "plan": plan.public_summary(),
                "applied": False,
                "no_op": plan.no_op,
            }
        authorizations = (
            {}
            if plan.no_op
            else self._authorize_effect_plans(
                request,
                plan.plan_id,
                plan.effect_plans,
                "research preparation",
            )
        )
        try:
            result = apply_research_run(
                plan,
                authorizations,
                expected_plan_id=request.expected_plan_id or "",
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
            "no_op": plan.no_op,
        }

    def _research_action(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"request_text", "working_directory"},
            optional={"project_id", "context_text"},
        )
        working_directory = Path(
            _string_argument(request.arguments, "working_directory")
        )
        if not working_directory.is_absolute():
            raise ApplicationServiceError("working_directory must be absolute")
        project_ref = request.arguments.get("project_id")
        if project_ref is not None:
            project_ref = _identifier_argument(request.arguments, "project_id")
        request_text = _string_argument(request.arguments, "request_text")
        context_text = request.arguments.get("context_text")
        if context_text is not None and not isinstance(context_text, str):
            raise ApplicationServiceError("context_text must be a string")
        try:
            try:
                match = resolve_current_project(
                    self._store,
                    working_directory=working_directory,
                    project_ref=project_ref,
                    request_text=request_text,
                )
            except ProjectContextError as exc:
                if not str(exc).startswith("project selection is ambiguous:"):
                    raise ApplicationServiceError(str(exc)) from exc
                intent = parse_research_intent(
                    self._repo_root,
                    request_text,
                    context_text=context_text,
                )
                if intent is None:
                    raise ApplicationServiceError(
                        "research action was not recognized"
                    )
                if request.apply:
                    raise ApplicationServiceError(
                        "research action needs one explicit project selection"
                    )
                return "choice-required", {
                    "route": intent.public_summary(),
                    "plan": None,
                    "applied": False,
                    "request_preserved": True,
                    "selection_reason": "multiple-projects-mentioned",
                    "navigation": project_navigation_menu(self._store),
                }
            if project_ref is not None and match is None:
                if request.apply:
                    raise ApplicationServiceError(
                        "research action project is not registered"
                    )
                intent = parse_research_intent(
                    self._repo_root,
                    request_text,
                    context_text=context_text,
                )
                if intent is None:
                    raise ApplicationServiceError(
                        "research action was not recognized"
                    )
                return "choice-required", {
                    "route": intent.public_summary(),
                    "plan": None,
                    "applied": False,
                    "request_preserved": True,
                    "selection_reason": "project-not-found",
                    "navigation": project_navigation_menu(self._store),
                }
            intent = parse_research_intent(
                self._repo_root,
                request_text,
                project_id=match.project.record_id if match is not None else None,
                context_text=context_text,
            )
        except (ResearchIntentError, ValueError) as exc:
            raise ApplicationServiceError(str(exc)) from exc
        if intent is None:
            raise ApplicationServiceError("research action was not recognized")
        route = intent.public_summary()
        if intent.needs_context:
            if request.apply:
                raise ApplicationServiceError(
                    "research action needs context before it can be applied"
                )
            data: dict[str, object] = {
                "route": route,
                "plan": None,
                "applied": False,
                "request_preserved": True,
            }
            if intent.needs_project:
                data["navigation"] = project_navigation_menu(self._store)
            return "choice-required", data
        try:
            plan = prepare_research_run(
                self._repo_root,
                self._store,
                self._ownership,
                intent.research_request(),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        next_stage = (
            "project-work-item-and-dispatch-planning"
            if intent.project_id is not None
            else "operator-mediated-or-client-research"
        )
        if not request.apply:
            return "planned", {
                "route": route,
                "plan": plan.public_summary(),
                "applied": False,
                "no_op": plan.no_op,
                "next_stage": next_stage,
                "dispatch_ready": False,
                "automatic_implementation": False,
            }
        authorizations = (
            {}
            if plan.no_op
            else self._authorize_effect_plans(
                request,
                plan.plan_id,
                plan.effect_plans,
                "natural-language research preparation",
            )
        )
        try:
            result = apply_research_run(
                plan,
                authorizations,
                expected_plan_id=request.expected_plan_id or "",
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {
            "route": route,
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
            "no_op": plan.no_op,
            "next_stage": next_stage,
            "dispatch_ready": False,
            "automatic_implementation": False,
        }

    def _import_research_response(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        try:
            plan = prepare_research_result_import(
                self._repo_root,
                self._store,
                self._ownership,
                request.arguments,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        if not request.apply:
            return "planned", {
                "plan": plan.public_summary(),
                "applied": False,
                "no_op": plan.no_op,
            }
        authorizations = (
            {}
            if plan.no_op
            else self._authorize_effect_plans(
                request,
                plan.plan_id,
                plan.effect_plans,
                "research response import",
            )
        )
        try:
            result = apply_research_result_import(
                plan,
                authorizations,
                expected_plan_id=request.expected_plan_id or "",
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
            "no_op": plan.no_op,
        }

    def _research_status(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError("research status is read-only")
        try:
            result = get_research_status(self._store, request.arguments)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"result": result}

    def _research_availability(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"execution_request"},
            optional={"platform_name"},
        )
        if request.apply:
            raise ApplicationServiceError("research availability is read-only")
        platform_name = request.arguments.get("platform_name")
        if platform_name is not None and not isinstance(platform_name, str):
            raise ApplicationServiceError("platform_name must be a string")
        try:
            plan = resolve_research_execution(
                load_research_execution_policy(self._repo_root),
                _object_argument(request.arguments, "execution_request"),
                platform_name=platform_name,
            )
            probe = probe_research_execution(plan)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        status = "ok" if probe.available or probe.optional else "degraded"
        return status, {
            "execution": plan.public_summary(),
            "availability": probe.public_summary(),
            "gemini_required": False,
            "authority_granted": False,
        }

    def _research_delegation_decision(
        self,
        arguments: Mapping[str, object],
    ):
        delegation = _object_argument(arguments, "delegation")
        _check_arguments(
            delegation,
            required={
                "session_id", "client_id", "capabilities",
                "max_parallel_agents", "work_class", "project_matched",
            },
        )
        project_matched = delegation.get("project_matched")
        if project_matched is not True:
            raise ApplicationServiceError(
                "native research dispatch requires a matched project"
            )
        profile = self._client_capability_profile(delegation)
        decision = decide_delegation(
            load_delegation_policy(self._repo_root),
            profile,
            work_class=_identifier_argument(delegation, "work_class"),
            project_matched=True,
        )
        if (
            not decision.delegation_required
            or not decision.execution_allowed
            or not decision.coordinator_only
        ):
            raise ApplicationServiceError(
                "native research delegation is unavailable for this client session"
            )
        return decision

    def _research_runtime_plan(
        self,
        arguments: Mapping[str, object],
    ):
        _check_arguments(
            arguments,
            required={
                "project_id", "work_item_id", "work_item_revision",
                "work_item_digest", "research_id", "task_plan_id", "prompts",
                "delegation", "executions",
            },
            optional={"max_concurrency"},
        )
        project_id = _identifier_argument(arguments, "project_id")
        if self._store.read("projects", project_id) is None:
            raise ApplicationServiceError("research runtime project is not registered")
        work_item_id = _identifier_argument(arguments, "work_item_id")
        record = self._store.read("work-items", work_item_id)
        if record is None:
            raise ApplicationServiceError("research runtime work item is not registered")
        try:
            work_item = parse_work_item(record.payload)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        work_item_revision = _nonnegative_integer_argument(arguments, "work_item_revision")
        work_item_digest = _string_argument(arguments, "work_item_digest")
        if (
            work_item.project_id != project_id
            or work_item.revision != work_item_revision
            or work_item.work_digest != work_item_digest
            or work_item.status not in ACTIVE_STATUSES
        ):
            raise ApplicationServiceError(
                "research runtime work item does not match the authoritative active record"
            )
        decision = self._research_delegation_decision(arguments)
        executions = _object_argument(arguments, "executions")
        if set(executions) != set(RESEARCH_DAG):
            raise ApplicationServiceError("research executions must cover every runtime role")
        policy = load_research_execution_policy(self._repo_root)
        execution_bindings = {}
        execution_identity = {}
        for role in RESEARCH_DAG:
            assignment = executions.get(role)
            if not isinstance(assignment, Mapping) or set(assignment) != {
                "worker_id", "execution_request", "provider_disclosure"
            }:
                raise ApplicationServiceError("research execution assignment is invalid")
            worker_id = assignment.get("worker_id")
            if not isinstance(worker_id, str) or not worker_id.strip():
                raise ApplicationServiceError("research execution worker id is invalid")
            disclosure = assignment.get("provider_disclosure")
            if not isinstance(disclosure, Mapping) or set(disclosure) != {
                "provider", "endpoint", "data_categories", "operation_scope",
                "retention_assumptions", "session_id", "remote",
            }:
                raise ApplicationServiceError("research provider disclosure is invalid")
            categories = disclosure.get("data_categories")
            if not isinstance(categories, list) or any(not isinstance(value, str) for value in categories):
                raise ApplicationServiceError("research provider data categories are invalid")
            try:
                provider_request = create_provider_request(
                    provider=str(disclosure.get("provider", "")),
                    endpoint=str(disclosure.get("endpoint", "")),
                    data_categories=tuple(categories),
                    operation_scope=str(disclosure.get("operation_scope", "")),
                    retention_assumptions=str(disclosure.get("retention_assumptions", "")),
                    session_id=str(disclosure.get("session_id", "")),
                    remote=disclosure.get("remote") is True,
                )
                execution_plan = resolve_research_execution(
                    policy,
                    assignment.get("execution_request") if isinstance(assignment.get("execution_request"), Mapping) else {},
                )
                probe = probe_research_execution(
                    execution_plan,
                    **(
                        {"executable_resolver": self._research_executable_resolver}
                        if self._research_executable_resolver is not None
                        else {}
                    ),
                )
            except ValueError as exc:
                raise ApplicationServiceError(str(exc)) from exc
            if (
                execution_plan.provider != provider_request.provider
                or execution_plan.provider_request_id != provider_request.request_id
                or execution_plan.session_id != provider_request.session_id
            ):
                raise ApplicationServiceError(
                    "research execution does not match its exact provider request"
                )
            execution_bindings[role] = (worker_id, execution_plan, provider_request, probe)
            execution_identity[role] = dict(assignment)
        if len({binding[0] for binding in execution_bindings.values()}) != len(RESEARCH_DAG):
            raise ApplicationServiceError("research role workers must be independent")
        execution_digest = hashlib.sha256(
            json.dumps(execution_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        prompts = _object_argument(arguments, "prompts")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in prompts.items()):
            raise ApplicationServiceError("research prompts must be a string map")
        max_concurrency = arguments.get("max_concurrency", 2)
        if not isinstance(max_concurrency, int) or isinstance(max_concurrency, bool):
            raise ApplicationServiceError("max_concurrency must be an integer")
        declared_parallelism = _object_argument(arguments, "delegation").get(
            "max_parallel_agents"
        )
        if (
            not isinstance(declared_parallelism, int)
            or isinstance(declared_parallelism, bool)
            or max_concurrency > declared_parallelism
        ):
            raise ApplicationServiceError(
                "research concurrency exceeds the declared client capability"
            )
        queue = AgentRuntimeQueue(
            self._store.data_root,
            project_id,
            load_scheduler_policy(self._repo_root),
        )
        try:
            plan = prepare_research_runtime_dispatch(
                queue,
                self._ownership,
                project_id=project_id,
                work_item_id=work_item_id,
                work_item_revision=work_item_revision,
                work_item_digest=work_item_digest,
                research_id=_identifier_argument(arguments, "research_id"),
                task_plan_id=_string_argument(arguments, "task_plan_id"),
                prompts={str(key): str(value) for key, value in prompts.items()},
                execution_assignments_digest=execution_digest,
                max_concurrency=max_concurrency,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return queue, plan, decision, execution_bindings

    def _research_dispatch(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        queue, plan, decision, execution_bindings = self._research_runtime_plan(request.arguments)
        role_execution = {
            role: {
                "worker_id": binding[0],
                "execution": binding[1].public_summary(),
                "availability": binding[3].public_summary(),
                "provider_request": binding[2].public_summary(),
                "host_override": role in self._research_execution_adapters,
            }
            for role, binding in execution_bindings.items()
        }
        plan_summary = {
            **plan.public_summary(),
            "delegation_mode": decision.selected_mode,
            "delegation_decision_digest": decision.decision_digest,
            "execution_adapter_available": all(
                role in self._research_execution_adapters or binding[3].available
                for role, binding in execution_bindings.items()
            ),
            "role_executions": role_execution,
            "authority_granted": False,
        }
        if not request.apply:
            return "planned", {"plan": plan_summary, "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact research runtime plan id"
            )
        if request.approval_id is None:
            raise ApplicationServiceError("research dispatch requires approval id")
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id, request.approval_id, approved=True
            ),
        )
        owner_tokens = {
            role: hashlib.sha256(
                f"{decision.decision_digest}:{role}".encode("utf-8")
            ).hexdigest()
            for role in RESEARCH_DAG
        }
        cancellation = threading.Event()
        adapters = {}
        provider_policy = load_provider_gate_policy(self._repo_root)
        for role, binding in execution_bindings.items():
            worker_id, execution_plan, provider_request, probe = binding
            approval = ProviderApproval(
                provider_request.request_id,
                provider_request.session_id,
                request.approval_id,
                approved=True,
            )
            try:
                provider_authorization = authorize_provider_request(
                    provider_policy,
                    provider_request,
                    approval=approval,
                )
            except ValueError as exc:
                raise ApplicationServiceError(str(exc)) from exc
            if role in self._research_execution_adapters:
                adapters[role] = bind_research_runtime_adapter(
                    self._research_execution_adapters[role],
                    execution_plan,
                    worker_id=worker_id,
                )
                continue
            if not probe.available:
                raise ApplicationServiceError(
                    f"native research execution is unavailable for role {role}"
                )
            factory_options = {
                "worker_id": worker_id,
                "runner": self._research_process_runners.get(role),
                "cancellation": cancellation,
            }
            if self._research_executable_resolver is not None:
                factory_options["executable_resolver"] = self._research_executable_resolver
            adapters[role] = create_research_runtime_adapter(
                execution_plan,
                provider_authorization,
                **factory_options,
            )
        with self._research_cancellation_lock:
            cancellation_key = (plan.project_id, plan.research_id)
            if cancellation_key in self._research_cancellations:
                raise ApplicationServiceError("research dispatch is already running")
            self._research_cancellations[cancellation_key] = cancellation
        try:
            result = dispatch_research_runtime(
                queue,
                plan,
                authorization,
                adapters=adapters,
                owner_tokens=owner_tokens,
                expected_plan_id=plan.plan_id,
                cancellation=cancellation.is_set,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        finally:
            with self._research_cancellation_lock:
                self._research_cancellations.pop((plan.project_id, plan.research_id), None)
        return "applied", {
            "plan": plan_summary,
            "result": result,
            "applied": True,
        }

    def _research_runtime_status(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id", "research_id"})
        if request.apply:
            raise ApplicationServiceError("research runtime status is read-only")
        project_id = _identifier_argument(request.arguments, "project_id")
        if self._store.read("projects", project_id) is None:
            raise ApplicationServiceError("research runtime project is not registered")
        queue = AgentRuntimeQueue(
            self._store.data_root,
            project_id,
            load_scheduler_policy(self._repo_root),
        )
        result = get_research_runtime_status(
            queue, _identifier_argument(request.arguments, "research_id")
        )
        with self._research_cancellation_lock:
            running = (project_id, str(result["research_id"])) in self._research_cancellations
        return "ok", {"result": {**result, "process_local_running": running}}

    def _research_cancel(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id", "research_id"})
        project_id = _identifier_argument(request.arguments, "project_id")
        research_id = _identifier_argument(request.arguments, "research_id")
        if self._store.read("projects", project_id) is None:
            raise ApplicationServiceError("research runtime project is not registered")
        identity = {
            "operation": "research.cancel",
            "project_id": project_id,
            "research_id": research_id,
        }
        plan_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not request.apply:
            return "planned", {
                "plan": {**identity, "plan_id": plan_id, "process_local": True},
                "applied": False,
            }
        if request.expected_plan_id != plan_id or request.approval_id is None:
            raise ApplicationServiceError(
                "cancel requires the exact plan id and approval id"
            )
        with self._research_cancellation_lock:
            signal = self._research_cancellations.get((project_id, research_id))
        if signal is None:
            return "unavailable", {
                "research_id": research_id,
                "cancellation_signalled": False,
                "process_local": True,
                "separate_process_supported": False,
                "reason": "no in-process research dispatch is running in this service instance",
            }
        with self._research_cancellation_lock:
            if signal is not None:
                signal.set()
        return ("cancelled" if signal is not None else "ok"), {
            "research_id": research_id,
            "cancellation_signalled": signal is not None,
            "process_local": True,
            "restart_persistent": False,
            "separate_process_supported": False,
        }

    def _research_resume(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        status, data = self._research_runtime_status(request)
        result = dict(data["result"])
        completed = bool(result.get("native_completion"))
        return status, {
            "result": result,
            "resume": {
                "no_op": completed,
                "new_exact_dispatch_plan_required": not completed,
                "automatic_process_restart_resume": False,
                "same_research_id_resume_supported": False,
                "new_research_id_required": not completed,
            },
        }

    def _retrieve_unified(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        """Compose current project evidence through one read-only retrieval service."""

        _check_arguments(request.arguments, required={"query"})
        if request.apply:
            raise ApplicationServiceError("unified retrieval is read-only")
        payload = _object_argument(request.arguments, "query")
        expected = {
            "schema_ref",
            "schema_version",
            "query_id",
            "text",
            "project_ids",
            "scope",
            "intent",
            "result_limit",
            "token_budget",
        }
        if set(payload) != expected:
            raise ApplicationServiceError("unified retrieval query fields are invalid")
        if (
            payload.get("schema_ref")
            != "schemas/unified-retrieval-query.schema.json"
            or payload.get("schema_version") != 1
        ):
            raise ApplicationServiceError("unified retrieval query schema is invalid")
        project_ids = payload.get("project_ids")
        if not isinstance(project_ids, list) or not project_ids:
            raise ApplicationServiceError("unified retrieval projects are required")
        policy = load_json(self._repo_root / "config" / "unified-retrieval.json")
        if len(project_ids) > int(policy["maximum_projects"]):
            raise ApplicationServiceError("unified retrieval project limit exceeded")
        result_limit = payload.get("result_limit")
        token_budget = payload.get("token_budget")
        if (
            not isinstance(result_limit, int)
            or isinstance(result_limit, bool)
            or result_limit > int(policy["maximum_hits"])
            or not isinstance(token_budget, int)
            or isinstance(token_budget, bool)
            or token_budget < int(policy["minimum_token_budget"])
            or token_budget > int(policy["maximum_token_budget"])
        ):
            raise ApplicationServiceError("unified retrieval budget is invalid")
        try:
            unified_request = create_unified_request(
                query_id=str(payload.get("query_id", "")),
                text=str(payload.get("text", "")),
                current_project_id=str(project_ids[0]),
                project_ids=tuple(str(item) for item in project_ids),
                scope=str(payload.get("scope", "")),
                intent=str(payload.get("intent", "")),
                result_limit=result_limit,
                token_budget=token_budget,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc

        batches = []
        domain_status: dict[str, str] = {}
        allowed_domains = set(INTENT_DOMAINS[unified_request.intent])
        per_domain_limit = min(result_limit, 100)
        for project_id in unified_request.project_ids:
            if "work" in allowed_domains:
                key = f"{project_id}:work"
                try:
                    work_arguments: dict[str, object] = {
                        "project_id": project_id,
                        "limit": per_domain_limit,
                    }
                    if unified_request.intent != "status":
                        work_arguments["text"] = unified_request.text
                    batch = batch_from_work_graph(
                        query_work_graph(self._store, work_arguments)
                    )
                    batches.append(batch)
                    domain_status[key] = "current" if batch.candidates else "empty"
                except ValueError:
                    domain_status[key] = "unavailable"

            if "code" in allowed_domains:
                key = f"{project_id}:code"
                try:
                    binding, source_root, state = self._registered_project_source(project_id)
                    authorization = self._source_code_adapter_authorization(
                        binding,
                        "retrieve",
                        request.approval_id,
                    )
                    code_query = parse_source_code_query(
                        {
                            "schema_ref": "schemas/source-code-query.schema.json",
                            "schema_version": 1,
                            "query_id": unified_request.query_id,
                            "project_id": project_id,
                            "text": unified_request.text,
                            "languages": [],
                            "path_prefix": None,
                            "include_content": True,
                            "limit": per_domain_limit,
                        }
                    )
                    batch = batch_from_source_code(
                        retrieve_source_code(
                            self._repo_root,
                            self._store.data_root,
                            binding,
                            source_root,
                            state.root_digest,
                            code_query,
                            authorization,
                        )
                    )
                    batches.append(batch)
                    domain_status[key] = "current" if batch.candidates else "empty"
                except ValueError as exc:
                    domain_status[key] = (
                        "blocked-stale" if "stale" in str(exc).casefold() else "unavailable"
                    )

            if "oracle" in allowed_domains:
                key = f"{project_id}:oracle"
                try:
                    oracle_plan = prepare_oracle_index(self._store.data_root, project_id)
                    oracle_result = search_oracle_metadata(
                        self._store.data_root,
                        project_id,
                        unified_request.text,
                        limit=per_domain_limit,
                    )
                    indexed_catalog_digest = str(
                        oracle_result.get("catalog_digest", "")
                    )
                    batch = batch_from_oracle(
                        oracle_result,
                        current_catalog_digest=oracle_plan.catalog_digest,
                        indexed_catalog_digest=indexed_catalog_digest,
                    )
                    batches.append(batch)
                    domain_status[key] = "current" if batch.candidates else "empty"
                except ValueError as exc:
                    domain_status[key] = (
                        "blocked-stale" if "stale" in str(exc).casefold() else "unavailable"
                    )

        if "knowledge" in allowed_domains:
            project_id = unified_request.project_ids[0]
            key = f"{project_id}:knowledge"
            try:
                catalog = self._information_catalog()
                hybrid_query = parse_hybrid_query(
                    {
                        "schema_ref": "schemas/hybrid-retrieval-query.schema.json",
                        "schema_version": 1,
                        "query_id": unified_request.query_id,
                        "text": unified_request.text,
                        "seed_record_ids": [],
                        "include_unavailable": False,
                        "limit": per_domain_limit,
                    }
                )
                batch = batch_from_hybrid(
                    retrieve_hybrid(
                        self._store.data_root,
                        catalog,
                        self._information_relations(),
                        hybrid_query,
                    ),
                    project_id,
                )
                batches.append(batch)
                domain_status[key] = "current" if batch.candidates else "empty"
            except ValueError as exc:
                domain_status[key] = (
                    "blocked-stale" if "stale" in str(exc).casefold() else "unavailable"
                )

        try:
            result = retrieve_unified(unified_request, batches)
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        next_actions = set()
        for key, state in domain_status.items():
            project_id, domain = key.split(":", 1)
            if state == "blocked-stale":
                next_actions.add(f"project.integrate:{project_id}")
            elif state == "unavailable" and domain == "knowledge":
                next_actions.add("knowledge.index")
            elif state == "unavailable" and domain == "code":
                next_actions.add(f"project.integrate:{project_id}")
            elif state == "unavailable" and domain == "oracle":
                next_actions.add(f"database.oracle.index:{project_id}")
        return "ok", {
            "result": result.as_dict(),
            "domain_status": dict(sorted(domain_status.items())),
            "next_actions": sorted(next_actions),
        }

    def _evaluate_retrieval_golden(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        """Evaluate complete engine observations without invoking a provider."""

        _check_arguments(
            request.arguments,
            required={"engine_profile_id", "observations"},
        )
        if request.apply:
            raise ApplicationServiceError("retrieval golden evaluation is read-only")
        engine_profile_id = _identifier_argument(
            request.arguments,
            "engine_profile_id",
        )
        golden_set = load_retrieval_golden_set(self._repo_root)
        try:
            observations = parse_retrieval_observations(
                request.arguments.get("observations"),
                golden_set,
            )
            result = evaluate_retrieval_golden_set(
                golden_set,
                observations,
                engine_profile_id=engine_profile_id,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "result": result,
            "suite": {
                "suite_id": golden_set.suite_id,
                "suite_digest": golden_set.suite_digest,
                "case_count": len(golden_set.cases),
            },
        }

    def _retrieval_scale_fixture(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        """Return only the digest-bound manifest for a lazy synthetic corpus."""

        _check_arguments(request.arguments, required={"profile_id"})
        if request.apply:
            raise ApplicationServiceError("retrieval scale fixtures are read-only")
        profile_id = _identifier_argument(request.arguments, "profile_id")
        try:
            manifest = build_retrieval_scale_manifest(
                load_retrieval_scale_policy(self._repo_root),
                profile_id,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"manifest": manifest}

    def _runtime_queue_action(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        action = request.operation.rsplit(".", 1)[1].replace("-", "_")
        queue, plan = prepare_runtime_queue_action(
            self._repo_root,
            self._store,
            self._ownership,
            action,
            request.arguments,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact runtime queue plan id"
            )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        result = apply_runtime_queue_action(queue, plan, authorization)
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
        }

    def _runtime_queue_status(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        if request.apply:
            raise ApplicationServiceError("runtime queue status is read-only")
        project_id = _identifier_argument(request.arguments, "project_id")
        if self._store.read("projects", project_id) is None:
            raise ApplicationServiceError("runtime queue project is not registered")
        queue = AgentRuntimeQueue(
            self._store.data_root,
            project_id,
            load_scheduler_policy(self._repo_root),
        )
        return "ok", {"result": queue.status()}

    def _oracle_project_binding(
        self,
        project_id: str,
        integration_id: str,
        binding_id: str,
    ) -> SourceBinding:
        if self._store.read("projects", project_id) is None:
            raise ApplicationServiceError("Oracle metadata project is not registered")
        if self._store.read("integrations", integration_id) is None:
            raise ApplicationServiceError("Oracle metadata integration is not registered")
        record = self._store.read("source-bindings", binding_id)
        if record is None:
            raise ApplicationServiceError("Oracle metadata binding is not registered")
        binding = parse_source_binding(record.payload)
        if (
            binding.source_kind not in {"database", "integration"}
            or binding.source_id != integration_id
            or binding.default_access != "read-only"
            or "write" in binding.capabilities
            or not {"read", "metadata"}.issubset(binding.capabilities)
        ):
            raise ApplicationServiceError(
                "Oracle metadata requires a read-only metadata binding"
            )
        return binding

    def _oracle_inspect(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id", "integration_id", "binding_id", "mode"},
        )
        if request.apply:
            raise ApplicationServiceError("Oracle metadata inspect is read-only")
        project_id = _identifier_argument(request.arguments, "project_id")
        integration_id = _identifier_argument(request.arguments, "integration_id")
        binding_id = _identifier_argument(request.arguments, "binding_id")
        binding = self._oracle_project_binding(project_id, integration_id, binding_id)
        mode = _string_argument(request.arguments, "mode")
        if mode not in {"select-compatible", "batch-open"}:
            raise ApplicationServiceError("Oracle metadata collection mode is invalid")
        template_id = "fetch-ddl" if mode == "select-compatible" else "batch-open"
        bind_values = (
            {
                "object_type": "TABLE",
                "object_name": "POLICY_PROBE",
                "owner": "POLICY_PROBE",
            }
            if template_id == "fetch-ddl"
            else {"object_type": "TABLE"}
        )
        try:
            authorization = require_oracle_metadata_template(
                template_id,
                bind_values,
                load_user_policies(self._store.data_root / "policies"),
                integration_id=integration_id,
                session_approved=request.approval_id is not None,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "result": {
                "project_id": project_id,
                "integration_id": integration_id,
                "binding_id": binding.binding_id,
                "binding_revision": binding.revision,
                "collection_mode": mode,
                "policy_permitted": authorization.permitted,
                "row_data_collected": False,
                "free_sql_allowed": False,
                "network_connection_opened": False,
            }
        }

    def _oracle_collect(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "project_id",
                "integration_id",
                "binding_id",
                "owners",
                "object_types",
                "mode",
                "complete",
            },
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        integration_id = _identifier_argument(request.arguments, "integration_id")
        binding_id = _identifier_argument(request.arguments, "binding_id")
        binding = self._oracle_project_binding(project_id, integration_id, binding_id)
        transport = self._oracle_metadata_transports.get(integration_id)
        if transport is None:
            raise ApplicationServiceError(
                "Oracle metadata transport must be explicitly registered"
            )
        if request.approval_id is None:
            raise ApplicationServiceError(
                "Oracle metadata collection requires network session approval"
            )
        mode = _string_argument(request.arguments, "mode")
        complete = request.arguments.get("complete")
        if not isinstance(complete, bool):
            raise ApplicationServiceError("complete must be boolean")
        policy = OracleCollectionPolicy(
            _string_tuple_argument(request.arguments, "owners"),
            _string_tuple_argument(request.arguments, "object_types"),
            mode,
        )
        if mode == "batch-open" and "execute" not in binding.capabilities:
            raise ApplicationServiceError(
                "Oracle batch metadata requires execute binding capability"
            )
        configured = load_json(self._repo_root / "config" / "oracle-metadata.json")
        allowed_types = configured.get("allowed_object_types")
        if (
            not isinstance(allowed_types, list)
            or not set(policy.object_types).issubset(set(allowed_types))
            or configured.get("row_data_allowed") is not False
            or configured.get("free_sql_allowed") is not False
        ):
            raise ApplicationServiceError(
                "Oracle metadata request exceeds the versioned policy"
            )
        template_id = "fetch-ddl" if mode == "select-compatible" else "batch-open"
        bind_values = (
            {
                "object_type": policy.object_types[0],
                "object_name": "POLICY_PROBE",
                "owner": policy.owners[0],
            }
            if template_id == "fetch-ddl"
            else {"object_type": policy.object_types[0]}
        )
        policies = load_user_policies(self._store.data_root / "policies")
        require_oracle_metadata_template(
            template_id,
            bind_values,
            policies,
            integration_id=integration_id,
            session_approved=request.approval_id is not None,
        )
        snapshot = collect_oracle_snapshot(
            project_id,
            integration_id,
            transport,
            policy,
            OracleReadAuthorization(
                binding.binding_id,
                binding.revision,
                "metadata-select" if mode == "select-compatible" else "metadata-batch-open",
                True,
            ),
            complete=complete,
            data_root=self._store.data_root,
        )
        plan = prepare_oracle_apply(self._store.data_root, snapshot)
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id or request.approval_id is None:
            raise ApplicationServiceError(
                "Oracle metadata apply requires the exact plan and approval id"
            )
        result = apply_oracle_plan(
            plan,
            OracleApplyAuthorization(plan.plan_id, request.approval_id, True),
        )
        return "applied", {"plan": plan.public_summary(), "result": result, "applied": True}

    def _oracle_status(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        if request.apply:
            raise ApplicationServiceError("Oracle metadata status is read-only")
        project_id = _identifier_argument(request.arguments, "project_id")
        project_root = self._store.data_root / "projects" / project_id
        oracle_root = project_root / "database" / "oracle"
        counts = {
            name: len(tuple((oracle_root / name).glob("*.json")))
            if (oracle_root / name).is_dir()
            else 0
            for name in ("snapshots", "objects", "revisions", "dependencies", "reports")
        }
        index_path = oracle_index_path(self._store.data_root, project_id)
        return "ok", {
            "result": {
                "project_id": project_id,
                "records": counts,
                "index_available": index_path.is_file() and not index_path.is_symlink(),
                "row_data_collected": False,
            }
        }

    def _oracle_index(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        project_id = _identifier_argument(request.arguments, "project_id")
        plan = prepare_oracle_index(self._store.data_root, project_id)
        summary = {
            "plan_id": plan.plan_id,
            "project_id": plan.project_id,
            "index_digest": plan.index_digest,
            "chunk_count": len(plan.chunks),
            "processed_chunk_count": plan.processed_chunk_count,
            "reused_chunk_count": plan.reused_chunk_count,
            "removed_chunk_count": plan.removed_chunk_count,
            "row_data_collected": False,
        }
        if not request.apply:
            return "planned", {"plan": summary, "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError("Oracle index apply requires the exact plan")
        result = apply_oracle_index(
            self._store.data_root,
            plan,
            OracleIndexAuthorization(plan.plan_id),
        )
        return "applied", {"plan": summary, "result": result, "applied": True}

    def _oracle_search(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id", "text"},
            optional={"owner", "object_type", "limit"},
        )
        if request.apply:
            raise ApplicationServiceError("Oracle metadata search is read-only")
        limit = request.arguments.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ApplicationServiceError("limit must be an integer")
        owner = request.arguments.get("owner")
        object_type = request.arguments.get("object_type")
        if owner is not None and not isinstance(owner, str):
            raise ApplicationServiceError("owner must be a string")
        if object_type is not None and not isinstance(object_type, str):
            raise ApplicationServiceError("object_type must be a string")
        result = search_oracle_metadata(
            self._store.data_root,
            _identifier_argument(request.arguments, "project_id"),
            _string_argument(request.arguments, "text"),
            owner=owner,
            object_type=object_type,
            limit=limit,
        )
        return "ok", {"result": result}

    def _oracle_dependencies(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id", "object_id"},
            optional={"direction", "max_depth"},
        )
        if request.apply:
            raise ApplicationServiceError("Oracle dependencies are read-only")
        max_depth = request.arguments.get("max_depth", 3)
        if not isinstance(max_depth, int) or isinstance(max_depth, bool):
            raise ApplicationServiceError("max_depth must be an integer")
        result = retrieve_oracle_dependencies(
            self._store.data_root,
            _identifier_argument(request.arguments, "project_id"),
            _string_argument(request.arguments, "object_id"),
            direction=str(request.arguments.get("direction", "outbound")),
            max_depth=max_depth,
        )
        return "ok", {"result": result}

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
        return "ok", project_navigation_menu(self._store)

    def _list_work(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"working_directory"},
            optional={"project_ref", "work_type", "lifecycle", "limit"},
        )
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        match = resolve_current_project(
            self._store,
            working_directory=self._absolute_path_argument(
                request.arguments,
                "working_directory",
            ),
            project_ref=(
                _string_argument(request.arguments, "project_ref")
                if "project_ref" in request.arguments
                else None
            ),
        )
        if match is None:
            project_ref = request.arguments.get("project_ref")
            return "ok", {
                **unmatched_project_context(),
                "work": None,
                "navigation": project_navigation_menu(self._store),
                "suggested_projects": (
                    suggest_projects(self._store, project_ref)
                    if isinstance(project_ref, str)
                    else []
                ),
            }
        work_type = request.arguments.get("work_type")
        if work_type is not None and not isinstance(work_type, str):
            raise ApplicationServiceError("work_type must be a string")
        lifecycle = request.arguments.get("lifecycle", "all")
        if not isinstance(lifecycle, str):
            raise ApplicationServiceError("lifecycle must be a string")
        limit = request.arguments.get("limit", 100)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ApplicationServiceError("limit must be an integer")
        return "ok", {
            **match.public_summary(self._store),
            "work": project_work_list(
                self._store,
                match.project.record_id,
                work_type=work_type,
                lifecycle=lifecycle,
                limit=limit,
            ),
        }

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
            project_ref = request.arguments.get("project_ref")
            return "ok", {
                **unmatched_project_context(),
                "navigation": project_navigation_menu(self._store),
                "suggested_projects": (
                    suggest_projects(self._store, project_ref)
                    if isinstance(project_ref, str)
                    else []
                ),
            }
        return "ok", match.public_summary(self._store)

    def _resume_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        match = self._project_context_match(request)
        if match is None:
            project_ref = request.arguments.get("project_ref")
            return "ok", {
                **unmatched_project_context(),
                "resume": None,
                "navigation": project_navigation_menu(self._store),
                "suggested_projects": (
                    suggest_projects(self._store, project_ref)
                    if isinstance(project_ref, str)
                    else []
                ),
            }
        return "ok", build_project_resume_summary(
            self._store,
            match,
            self._repo_root,
        )

    def _client_capability_profile(
        self,
        arguments: Mapping[str, object],
    ) -> ClientCapabilityProfile:
        capabilities = _object_argument(arguments, "capabilities")
        max_parallel_agents = arguments.get("max_parallel_agents")
        if (
            not isinstance(max_parallel_agents, int)
            or isinstance(max_parallel_agents, bool)
        ):
            raise ApplicationServiceError("max_parallel_agents must be an integer")
        return create_client_capability_profile(
            load_client_capability_policy(self._repo_root),
            session_id=_string_argument(arguments, "session_id"),
            client_id=_identifier_argument(arguments, "client_id"),
            capabilities=capabilities,
            max_parallel_agents=max_parallel_agents,
        )

    def _client_capabilities(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "session_id",
                "client_id",
                "capabilities",
                "max_parallel_agents",
            },
        )
        if request.apply:
            raise ApplicationServiceError("client capability declaration is read-only")
        profile = self._client_capability_profile(request.arguments)
        return "ok", {"profile": profile.as_dict()}

    def _client_delegation(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "session_id",
                "client_id",
                "capabilities",
                "max_parallel_agents",
                "work_class",
                "project_matched",
            },
        )
        if request.apply:
            raise ApplicationServiceError("client delegation decision is read-only")
        project_matched = request.arguments.get("project_matched")
        if not isinstance(project_matched, bool):
            raise ApplicationServiceError("project_matched must be boolean")
        profile = self._client_capability_profile(request.arguments)
        policy = load_delegation_policy(self._repo_root)
        decision = decide_delegation(
            policy,
            profile,
            work_class=_identifier_argument(request.arguments, "work_class"),
            project_matched=project_matched,
        )
        degradation: Mapping[str, object] | None = None
        status = "ok"
        if decision.delegation_required and not decision.execution_allowed:
            status = "blocked"
            degradation = {
                "code": "delegation-unavailable",
                "execution_blocked": True,
                "user_visible_notice_required": True,
            }
        elif (
            decision.delegation_required
            and decision.selected_mode != "native-parallel"
        ):
            status = "degraded"
            degradation = {
                "code": decision.selected_mode,
                "execution_blocked": False,
                "user_visible_notice_required": True,
            }
        return status, {
            "profile": profile.as_dict(),
            "decision": decision.as_dict(),
            "coordinator_boundary": {
                "responsibilities": list(policy.coordinator_responsibilities),
                "prohibited_direct_actions": list(
                    policy.coordinator_prohibited_actions
                ),
            },
            "degradation": degradation,
            "authority_granted": False,
        }

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

    def _resolve_model(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required=set(),
            optional={"workload", "role", "available_bindings", "authorized_refs"},
        )
        if request.apply:
            raise ApplicationServiceError("model resolution is read-only")
        workload = request.arguments.get("workload")
        role = request.arguments.get("role")
        if workload is not None and not isinstance(workload, str):
            raise ApplicationServiceError("workload must be a string")
        if role is not None and not isinstance(role, str):
            raise ApplicationServiceError("role must be a string")
        bindings = request.arguments.get("available_bindings", {})
        if not isinstance(bindings, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in bindings.items()
        ):
            raise ApplicationServiceError("available_bindings must be a string map")
        refs = request.arguments.get("authorized_refs", [])
        if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
            raise ApplicationServiceError("authorized_refs must be a string list")
        selection = resolve_model_route(
            load_model_routing_policy(self._repo_root),
            workload=workload,
            role=role,
            available_bindings=bindings,
            authorized_refs=tuple(refs),
        )
        return "ok", {"selection": selection.as_dict()}

    def _model_inventory(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"models"})
        entries = request.arguments.get("models")
        if not isinstance(entries, list):
            raise ApplicationServiceError("models must be a list")
        plan = prepare_model_inventory(
            self._store,
            self._ownership,
            entries,
        )
        if not request.apply:
            return (
                "planned" if plan.effect_plans else "ok",
                {
                    "plan": plan.public_summary(),
                    "no_op": not plan.effect_plans,
                    "applied": False,
                },
            )
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            tuple(item.mutation for item in plan.effect_plans),
            "model inventory",
        )
        applied = apply_model_inventory(self._store, plan, authorizations)
        return "applied", {
            "plan": plan.public_summary(),
            "applied_records": list(applied),
            "applied": True,
        }

    def _list_models(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set())
        if request.apply:
            raise ApplicationServiceError("model list is read-only")
        models = list_model_inventory(self._store)
        health_by_model = {
            str(item["model_ref"]): item
            for item in list_model_health(
                self._repo_root,
                self._store,
                now=datetime.now(timezone.utc),
            )
        }
        summaries = [
            {
                **model,
                "health_state": (
                    health_by_model.get(
                        str(model["model_ref"]),
                        {"effective_state": "candidate"},
                    )["effective_state"]
                    if model["enabled"]
                    else "disabled"
                ),
            }
            for model in models
        ]
        return "ok", {
            "model_count": len(summaries),
            "models": summaries,
            "credential_values_included": False,
            "endpoints_included": False,
        }

    def _model_health(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "model_ref",
                "endpoint",
                "retention_assumptions",
                "session_id",
            },
            optional={"force_retest"},
        )
        model_ref = _identifier_argument(request.arguments, "model_ref")
        endpoint = _string_argument(request.arguments, "endpoint")
        retention = _string_argument(request.arguments, "retention_assumptions")
        session_id = _string_argument(request.arguments, "session_id")
        force_retest = request.arguments.get("force_retest", False)
        if not isinstance(force_retest, bool):
            raise ApplicationServiceError("force_retest must be boolean")
        now = datetime.now(timezone.utc)
        plan = prepare_model_health_action(
            self._repo_root,
            self._store,
            model_ref,
            endpoint=endpoint,
            retention_assumptions=retention,
            session_id=session_id,
            now=now,
            force_retest=force_retest,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "model health apply requires the exact plan id"
            )
        approval = ProviderApproval(
            plan.provider_request.request_id,
            plan.provider_request.session_id,
            request.approval_id or "",
            bool(request.approval_id),
        )
        try:
            authorization = authorize_provider_request(
                load_provider_gate_policy(self._repo_root),
                plan.provider_request,
                approval=approval,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        inventory = self._store.read("model-inventory", model_ref)
        if inventory is None:
            raise ApplicationServiceError("model inventory record was not found")
        model = parse_model_inventory_record(inventory.payload)
        probe = self._model_health_probes.get(str(model["provider_ref"]))
        if probe is None:
            raise ApplicationServiceError(
                "model health probe adapter is unavailable for this provider"
            )
        observation = probe.probe(model, load_model_health_policy(self._repo_root), authorization)
        result = persist_model_health_observation(
            self._store,
            model,
            load_model_health_policy(self._repo_root),
            observation,
            checked_at=datetime.now(timezone.utc),
        )
        return "applied", {
            "plan": plan.public_summary(),
            "health": result,
            "applied": True,
        }

    def _list_model_health(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set())
        if request.apply:
            raise ApplicationServiceError("model health list is read-only")
        records = list_model_health(
            self._repo_root,
            self._store,
            now=datetime.now(timezone.utc),
        )
        return "ok", {
            "health_count": len(records),
            "health": list(records),
            "credential_values_included": False,
            "response_content_included": False,
        }

    def _model_benchmark_suite(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        project_id = _identifier_argument(request.arguments, "project_id")
        plan = prepare_project_benchmark_suite(
            self._repo_root,
            self._store,
            project_id,
        )
        if not request.apply:
            return (
                "ok" if plan.effect_plan is None else "planned",
                {
                    "plan": plan.public_summary(),
                    "no_op": plan.effect_plan is None,
                    "applied": False,
                },
            )
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "model benchmark apply requires the exact plan id"
            )
        authorization = None
        if plan.effect_plan is not None:
            authorization = self._authorize_record_plans(
                request,
                plan.plan_id,
                (plan.effect_plan,),
            )[plan.effect_plan.mutation.plan_id]
        suite = apply_project_benchmark_suite(
            self._store,
            plan,
            authorization,
        )
        return "applied", {
            "plan": plan.public_summary(),
            "suite_id": suite["suite_id"],
            "suite_revision": suite["suite_revision"],
            "suite_digest": suite["suite_digest"],
            "applied": plan.effect_plan is not None,
        }

    def _list_model_benchmarks(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required=set(), optional={"project_id"})
        if request.apply:
            raise ApplicationServiceError("model benchmark list is read-only")
        project_id = request.arguments.get("project_id")
        if project_id is not None:
            project_id = _identifier_argument(request.arguments, "project_id")
        suites = list_project_benchmark_suites(
            self._repo_root,
            self._store,
            project_id=project_id,
        )
        return "ok", {
            "suite_count": len(suites),
            "suites": list(suites),
            "source_content_included": False,
            "paths_disclosed": False,
            "remote_call_performed": False,
        }

    def _benchmark_provider_authorization(
        self,
        request: ServiceRequest,
        model: Mapping[str, object],
    ):
        disclosure = request.arguments.get("provider_disclosure")
        if model.get("remote") is not True:
            if disclosure is not None:
                raise ApplicationServiceError(
                    "local benchmark accepts no provider disclosure"
                )
            return None, None
        if not isinstance(disclosure, Mapping) or set(disclosure) != {
            "provider",
            "endpoint",
            "data_categories",
            "operation_scope",
            "retention_assumptions",
            "session_id",
            "remote",
            "authorization_ref",
        }:
            raise ApplicationServiceError(
                "remote benchmark requires exact provider disclosure"
            )
        categories = disclosure.get("data_categories")
        if not isinstance(categories, list) or any(
            not isinstance(item, str) for item in categories
        ):
            raise ApplicationServiceError(
                "provider data_categories must be a string list"
            )
        try:
            provider_request = create_provider_request(
                provider=str(disclosure.get("provider", "")),
                endpoint=str(disclosure.get("endpoint", "")),
                data_categories=tuple(categories),
                operation_scope=str(disclosure.get("operation_scope", "")),
                retention_assumptions=str(
                    disclosure.get("retention_assumptions", "")
                ),
                session_id=str(disclosure.get("session_id", "")),
                remote=disclosure.get("remote") is True,
            )
            authorization = authorize_provider_request(
                load_provider_gate_policy(self._repo_root),
                provider_request,
                approval=ProviderApproval(
                    provider_request.request_id,
                    provider_request.session_id,
                    request.approval_id or "",
                    bool(request.approval_id),
                ),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        authorization_ref = disclosure.get("authorization_ref")
        if not isinstance(authorization_ref, str) or not IDENTIFIER.fullmatch(
            authorization_ref
        ):
            raise ApplicationServiceError(
                "provider authorization_ref must be a portable identifier"
            )
        return authorization, authorization_ref

    @staticmethod
    def _benchmark_timestamp(value: object, label: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ApplicationServiceError(f"{label} must be an ISO 8601 timestamp")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApplicationServiceError(
                f"{label} must be an ISO 8601 timestamp"
            ) from exc
        if timestamp.tzinfo is None:
            raise ApplicationServiceError(f"{label} must carry a timezone")
        return timestamp

    def _prepare_model_benchmark_execution(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "project_id",
                "suite_id",
                "model_ref",
                "execution_profile",
                "workload_id",
                "repetitions",
                "model_assignment_id",
                "now",
            },
            optional={"timeout_ms", "provider_disclosure"},
        )
        if request.apply:
            raise ApplicationServiceError("benchmark preparation is read-only")
        project_id = _identifier_argument(request.arguments, "project_id")
        suite_id = _identifier_argument(request.arguments, "suite_id")
        model_ref = _identifier_argument(request.arguments, "model_ref")
        try:
            authoritative = resolve_authoritative_benchmark_inputs(
                self._repo_root,
                self._store,
                project_id=project_id,
                suite_id=suite_id,
                model_ref=model_ref,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        host = self._model_benchmark_hosts.get(model_ref)
        if host is None:
            return "blocked", {
                "reason_code": "benchmark-execution-host-unavailable",
                "model_ref": model_ref,
                "durable_exactly_once_host": False,
                "execution_performed": False,
                "provider_call_performed": False,
                "grants_authority": False,
            }
        try:
            host_descriptor = validate_benchmark_execution_host(
                host,
                model_ref=model_ref,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        model = authoritative.model
        authorization, authorization_ref = self._benchmark_provider_authorization(
            request, model
        )
        repetitions = request.arguments.get("repetitions")
        if not isinstance(repetitions, int) or isinstance(repetitions, bool):
            raise ApplicationServiceError("repetitions must be an integer")
        timeout = request.arguments.get("timeout_ms")
        if timeout is not None and (
            not isinstance(timeout, int) or isinstance(timeout, bool)
        ):
            raise ApplicationServiceError("timeout_ms must be an integer or null")
        try:
            plan = prepare_model_benchmark_run_from_store(
                self._repo_root,
                self._store,
                project_id=project_id,
                suite_id=suite_id,
                model_ref=model_ref,
                execution_profile=_object_argument(
                    request.arguments, "execution_profile"
                ),
                execution_host_descriptor=host_descriptor,
                workload_id=_identifier_argument(request.arguments, "workload_id"),
                repetitions=repetitions,
                model_assignment_id=_identifier_argument(
                    request.arguments, "model_assignment_id"
                ),
                timeout_ms=timeout,
                now=self._benchmark_timestamp(request.arguments.get("now"), "now"),
                provider_authorization=authorization,
                provider_authorization_ref=authorization_ref,
                provider_approval_id=(
                    request.approval_id if model["remote"] is True else None
                ),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "planned", {
            "plan": plan,
            "expected_plan_id": plan["plan_digest"],
            "execution_host_digest": plan["execution_host_digest"],
            "host_claimed": False,
            "provider_call_performed": False,
            "execution_performed": False,
            "grants_authority": False,
        }

    def _execute_model_benchmark(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "plan",
                "project_id",
                "suite_id",
                "model_ref",
                "execution_profile",
                "observed_at",
            },
            optional={"provider_disclosure"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        suite_id = _identifier_argument(request.arguments, "suite_id")
        model_ref = _identifier_argument(request.arguments, "model_ref")
        try:
            authoritative = resolve_authoritative_benchmark_inputs(
                self._repo_root,
                self._store,
                project_id=project_id,
                suite_id=suite_id,
                model_ref=model_ref,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        model = authoritative.model
        host = self._model_benchmark_hosts.get(model_ref)
        if host is None:
            return "blocked", {
                "reason_code": "benchmark-execution-host-unavailable",
                "model_ref": model_ref,
                "durable_exactly_once_host": False,
                "execution_performed": False,
                "provider_call_performed": False,
                "grants_authority": False,
            }
        if not request.apply:
            raise ApplicationServiceError(
                "benchmark execution requires explicit --apply"
            )
        plan = _object_argument(request.arguments, "plan")
        if request.expected_plan_id != plan.get("plan_digest"):
            raise ApplicationServiceError(
                "benchmark execution requires the exact plan digest"
            )
        if request.approval_id is None:
            raise ApplicationServiceError(
                "benchmark execution requires explicit approval id"
            )
        authorization, authorization_ref = self._benchmark_provider_authorization(
            request, model
        )
        try:
            output = execute_model_benchmark_run_from_store(
                self._repo_root,
                self._store,
                plan,
                project_id=project_id,
                suite_id=suite_id,
                model_ref=model_ref,
                expected_plan_id=str(plan.get("plan_id", "")),
                execution_profile=_object_argument(
                    request.arguments, "execution_profile"
                ),
                execution_host=host,
                execution_authorization_digest=build_execution_authorization_digest(
                    plan_digest=str(plan.get("plan_digest", "")),
                    approval_id=request.approval_id,
                ),
                observed_at=self._benchmark_timestamp(
                    request.arguments.get("observed_at"), "observed_at"
                ),
                provider_authorization=authorization,
                provider_authorization_ref=authorization_ref,
                provider_approval_id=(
                    request.approval_id if model["remote"] is True else None
                ),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return ("applied" if output.execution_performed else "ok"), {
            "result": output.as_dict(),
            "durable_exactly_once_host": True,
            "execution_performed": output.execution_performed,
            "persisted": False,
            "grants_authority": False,
        }

    def _autonomy_status(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"plan", "iterations", "observed_at"},
            optional={"cancellation_record"},
        )
        if request.apply:
            raise ApplicationServiceError("autonomy status is read-only")
        iterations = request.arguments.get("iterations")
        if not isinstance(iterations, list):
            raise ApplicationServiceError("iterations must be a list")
        cancellation = request.arguments.get("cancellation_record")
        if cancellation is not None and not isinstance(cancellation, Mapping):
            raise ApplicationServiceError("cancellation_record must be an object")
        try:
            status = build_measured_loop_status(
                load_measured_loop_policy(self._repo_root),
                _object_argument(request.arguments, "plan"),
                iterations,
                observed_at=_string_argument(request.arguments, "observed_at"),
                cancellation_record=cancellation,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"status": status.as_dict(), "grants_authority": False}

    def _autonomy_morning(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"status", "generated_at"})
        if request.apply:
            raise ApplicationServiceError("autonomy morning digest is read-only")
        try:
            digest = build_morning_digest(
                _object_argument(request.arguments, "status"),
                generated_at=_string_argument(request.arguments, "generated_at"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"digest": digest.as_dict(), "grants_authority": False}

    def _autonomy_admission(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "plan",
                "status",
                "iterations",
                "observed_at",
                "requested_claims",
                "active_claims",
                "cpu_pressure_basis_points",
                "ram_pressure_basis_points",
                "provider_required",
                "provider_quota_remaining_basis_points",
                "cost_headroom_microunits",
                "failure_pressure_basis_points",
            },
            optional={"cancellation_record"},
        )
        if request.apply:
            raise ApplicationServiceError("autonomy admission is read-only")
        integer_names = (
            "requested_claims",
            "active_claims",
            "cpu_pressure_basis_points",
            "ram_pressure_basis_points",
            "cost_headroom_microunits",
            "failure_pressure_basis_points",
        )
        values = {name: request.arguments.get(name) for name in integer_names}
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in values.values()
        ):
            raise ApplicationServiceError("autonomy admission counters are invalid")
        provider_required = request.arguments.get("provider_required")
        if not isinstance(provider_required, bool):
            raise ApplicationServiceError("provider_required must be boolean")
        quota = request.arguments.get("provider_quota_remaining_basis_points")
        if quota is not None and (
            not isinstance(quota, int) or isinstance(quota, bool)
        ):
            raise ApplicationServiceError(
                "provider quota must be an integer or null"
            )
        iterations = request.arguments.get("iterations")
        if not isinstance(iterations, list):
            raise ApplicationServiceError("iterations must be a list")
        cancellation = request.arguments.get("cancellation_record")
        if cancellation is not None and not isinstance(cancellation, Mapping):
            raise ApplicationServiceError("cancellation_record must be an object")
        try:
            decision = decide_admission(
                load_measured_loop_policy(self._repo_root),
                _object_argument(request.arguments, "plan"),
                _object_argument(request.arguments, "status"),
                iterations=iterations,
                cancellation_record=cancellation,
                observed_at=_string_argument(request.arguments, "observed_at"),
                requested_claims=values["requested_claims"],
                active_claims=values["active_claims"],
                cpu_pressure_basis_points=values["cpu_pressure_basis_points"],
                ram_pressure_basis_points=values["ram_pressure_basis_points"],
                provider_required=provider_required,
                provider_quota_remaining_basis_points=quota,
                cost_headroom_microunits=values["cost_headroom_microunits"],
                failure_pressure_basis_points=values[
                    "failure_pressure_basis_points"
                ],
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"admission": decision.as_dict(), "grants_authority": False}

    def _decide_model(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "project_id",
                "client_id",
                "workload",
                "role",
                "available_bindings",
                "now",
                "input_token_budget",
                "output_token_budget",
            },
            optional={
                "price_catalog_id",
                "maximum_cost_microunits",
                "maximum_latency_ms",
                "excluded_model_refs",
            },
        )
        if request.apply:
            raise ApplicationServiceError("model decision is read-only")
        project_id = _identifier_argument(request.arguments, "project_id")
        client_id = _identifier_argument(request.arguments, "client_id")
        workload = _identifier_argument(request.arguments, "workload")
        role = _identifier_argument(request.arguments, "role")
        bindings = request.arguments.get("available_bindings")
        if not isinstance(bindings, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in bindings.items()
        ):
            raise ApplicationServiceError("available_bindings must be a string map")
        now_value = _string_argument(request.arguments, "now")
        try:
            now = datetime.fromisoformat(now_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApplicationServiceError("now must be an ISO 8601 timestamp") from exc
        if now.tzinfo is None:
            raise ApplicationServiceError("now must carry a timezone")
        input_budget = request.arguments.get("input_token_budget")
        output_budget = request.arguments.get("output_token_budget")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (input_budget, output_budget)
        ):
            raise ApplicationServiceError("model token budgets are invalid")
        excluded = request.arguments.get("excluded_model_refs", [])
        if not isinstance(excluded, list) or any(
            not isinstance(value, str) for value in excluded
        ):
            raise ApplicationServiceError(
                "excluded_model_refs must be a string list"
            )
        price_catalog_id = request.arguments.get("price_catalog_id")
        if price_catalog_id is not None:
            price_catalog_id = _identifier_argument(
                request.arguments,
                "price_catalog_id",
            )
        maximum_cost = request.arguments.get("maximum_cost_microunits")
        maximum_latency = request.arguments.get("maximum_latency_ms")
        try:
            decision = decide_model_assignment_from_store(
                self._repo_root,
                self._store,
                project_id=project_id,
                client_id=client_id,
                workload=workload,
                role=role,
                available_bindings=bindings,
                price_catalog_id=price_catalog_id,
                now=now,
                input_token_budget=input_budget,
                output_token_budget=output_budget,
                maximum_cost_microunits=maximum_cost,
                maximum_latency_ms=maximum_latency,
                excluded_model_refs=excluded,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"decision": decision.as_dict()}

    def _decide_task_plan_models(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "project_id",
                "client_id",
                "task_plan",
                "step_workloads",
                "available_bindings",
                "now",
                "input_token_budget",
                "output_token_budget",
            },
            optional={
                "price_catalog_id",
                "maximum_cost_microunits",
                "maximum_latency_ms",
            },
        )
        if request.apply:
            raise ApplicationServiceError("task model decision is read-only")
        try:
            task_plan = parse_task_plan(request.arguments["task_plan"])
        except ValueError as exc:
            raise ApplicationServiceError("task plan is invalid") from exc
        step_workloads = request.arguments.get("step_workloads")
        bindings = request.arguments.get("available_bindings")
        if not isinstance(step_workloads, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in step_workloads.items()
        ):
            raise ApplicationServiceError("step_workloads must be a string map")
        if not isinstance(bindings, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in bindings.items()
        ):
            raise ApplicationServiceError("available_bindings must be a string map")
        now_value = _string_argument(request.arguments, "now")
        try:
            now = datetime.fromisoformat(now_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApplicationServiceError("now must be an ISO 8601 timestamp") from exc
        if now.tzinfo is None:
            raise ApplicationServiceError("now must carry a timezone")
        input_budget = request.arguments.get("input_token_budget")
        output_budget = request.arguments.get("output_token_budget")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (input_budget, output_budget)
        ):
            raise ApplicationServiceError("model token budgets are invalid")
        price_catalog_id = request.arguments.get("price_catalog_id")
        if price_catalog_id is not None:
            price_catalog_id = _identifier_argument(
                request.arguments,
                "price_catalog_id",
            )
        try:
            assignments = decide_task_plan_model_assignments_from_store(
                self._repo_root,
                self._store,
                project_id=_identifier_argument(request.arguments, "project_id"),
                client_id=_identifier_argument(request.arguments, "client_id"),
                task_plan=task_plan,
                step_workloads=step_workloads,
                available_bindings=bindings,
                price_catalog_id=price_catalog_id,
                now=now,
                input_token_budget=input_budget,
                output_token_budget=output_budget,
                maximum_cost_microunits=request.arguments.get(
                    "maximum_cost_microunits"
                ),
                maximum_latency_ms=request.arguments.get("maximum_latency_ms"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "assignments": assignments.as_dict(),
            "decisions": [
                decision.as_dict() for decision in assignments.decisions
            ],
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

    def _integrate_project(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required=set(),
            optional={"source_root", "project_id", "scan_mode"},
        )
        has_source = "source_root" in request.arguments
        has_project = "project_id" in request.arguments
        if has_source == has_project:
            raise ApplicationServiceError(
                "provide exactly one source_root or project_id"
            )
        source_root = (
            self._absolute_path_argument(request.arguments, "source_root")
            if has_source
            else None
        )
        project_id = (
            _identifier_argument(request.arguments, "project_id")
            if has_project
            else None
        )
        scan_mode = request.arguments.get("scan_mode", "manual")
        if not isinstance(scan_mode, str):
            raise ApplicationServiceError("scan_mode must be manual or automatic")
        try:
            plan = prepare_project_integration(
                self._repo_root,
                self._store,
                source_root=source_root,
                project_id=project_id,
                scan_mode=scan_mode,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        summary = plan.public_summary()
        if plan.no_op:
            if request.apply or request.expected_plan_id is not None:
                raise ApplicationServiceError(
                    "current project integration has no changes to apply"
                )
            return "ok", {"plan": summary, "applied": False, "no_op": True}
        if not request.apply:
            return "planned", {"plan": summary, "applied": False, "no_op": False}
        record_authorizations = self._authorize_record_plans(
            request,
            plan.plan_id,
            plan.record_plans,
        )
        index_authorization = None
        if plan.index_plan is not None:
            index_authorization = authorize_mutation(
                plan.index_plan.mutation,
                dry_run=DryRunEvidence(
                    plan.index_plan.mutation.plan_id,
                    verified=True,
                ),
            )
        source_code_index_authorization = None
        if plan.source_code_index_plan is not None:
            source_code_index_authorization = authorize_mutation(
                plan.source_code_index_plan.mutation,
                dry_run=DryRunEvidence(
                    plan.source_code_index_plan.mutation.plan_id,
                    verified=True,
                ),
            )
        try:
            result = apply_project_integration(
                self._repo_root,
                self._store,
                plan,
                record_authorizations,
                index_authorization,
                source_code_index_authorization,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {
            "plan": summary,
            **result.public_summary(),
            "applied": True,
            "no_op": False,
        }

    def _registered_project_source(self, project_id: str):
        project = self._store.read("projects", project_id)
        if project is None:
            raise ApplicationServiceError("project is not registered")
        source_refs = project.payload.get("source_refs")
        if not isinstance(source_refs, list) or len(source_refs) != 1:
            raise ApplicationServiceError(
                "source code operations require one project source"
            )
        binding_record = self._store.read("source-bindings", str(source_refs[0]))
        if binding_record is None:
            raise ApplicationServiceError("project source binding is missing")
        binding = parse_source_binding(binding_record.payload)
        state_record = self._store.read("source-states", binding.binding_id)
        if state_record is None:
            raise ApplicationServiceError(
                "project source state is missing; integrate the project first"
            )
        state = parse_source_state(state_record.payload)
        source_root = Path(binding.locator.value)
        if not source_root.is_absolute():
            raise ApplicationServiceError("project source locator is invalid")
        return binding, source_root.resolve(), state

    def _source_code_adapter_authorization(
        self,
        binding: SourceBinding,
        operation: str,
        approval_id: str | None,
    ):
        adapter_request = prepare_adapter_operation(
            LOCAL_SOURCE_CODE_ADAPTER,
            binding,
            operation,
            load_user_policies(self._store.data_root / "policies"),
        )
        approval = None
        if approval_id is not None:
            approval = AdapterApproval(
                adapter_request.request_id,
                approval_id,
                True,
            )
        return authorize_adapter_operation(adapter_request, approval)

    def _index_source_code(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"project_id"})
        project_id = _identifier_argument(request.arguments, "project_id")
        binding, source_root, state = self._registered_project_source(project_id)
        summary = source_code_index_summary(
            self._repo_root,
            self._store.data_root,
            project_id,
            binding_id=binding.binding_id,
            binding_revision=binding.revision,
            source_digest=state.root_digest,
        )
        if source_code_index_is_current(
            self._repo_root,
            self._store.data_root,
            project_id,
            binding.binding_id,
            state.root_digest,
            binding_revision=binding.revision,
        ):
            if request.apply or request.expected_plan_id is not None:
                raise ApplicationServiceError(
                    "current source code index has no changes to apply"
                )
            return "ok", {"index": summary, "applied": False, "no_op": True}
        authorization = self._source_code_adapter_authorization(
            binding,
            "index",
            request.approval_id,
        )
        discovery = DiscoveryResult(
            binding.binding_id,
            binding.source_id,
            binding.revision,
            state.root_digest,
            state.files,
            state.technologies,
            {
                "blocked": 0,
                "symlink": 0,
                "too_large": 0,
                "unstable": 0,
                "unreadable": 0,
            },
        )
        try:
            plan = prepare_source_code_index(
                self._repo_root,
                self._store.data_root,
                project_id,
                binding,
                source_root,
                discovery,
                self._ownership,
                authorization,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        if not request.apply:
            return "planned", {
                "plan": plan.public_summary(),
                "applied": False,
                "no_op": False,
            }
        if request.expected_plan_id != plan.plan_id:
            raise ApplicationServiceError(
                "apply requires the exact source code index plan id"
            )
        mutation_authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        try:
            result = apply_source_code_index(
                self._store.data_root,
                plan,
                mutation_authorization,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "applied", {
            "plan": plan.public_summary(),
            "result": result,
            "applied": True,
            "no_op": False,
        }

    def _search_source_code(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"query"})
        if request.apply:
            raise ApplicationServiceError("read operation cannot be applied")
        try:
            query = parse_source_code_query(
                _object_argument(request.arguments, "query")
            )
            binding, source_root, state = self._registered_project_source(
                query.project_id
            )
            authorization = self._source_code_adapter_authorization(
                binding,
                "retrieve",
                request.approval_id,
            )
            result = retrieve_source_code(
                self._repo_root,
                self._store.data_root,
                binding,
                source_root,
                state.root_digest,
                query,
                authorization,
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {"result": result}

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

    def _migrate_project_capsules(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"backup_path"})
        plan = prepare_project_capsule_migration(
            self._store.data_root,
            self._absolute_path_argument(request.arguments, "backup_path"),
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "project capsule migration",
        )
        result = apply_project_capsule_migration(
            plan,
            authorizations,
            self._ownership,
        )
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _export_project_capsule(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={"project_id", "archive_path", "mode"},
        )
        project_id = _identifier_argument(request.arguments, "project_id")
        mode = _string_argument(request.arguments, "mode")
        plan = prepare_project_capsule_export(
            self._store.data_root,
            project_id,
            self._absolute_path_argument(request.arguments, "archive_path"),
            mode,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            (plan.mutation,),
            "project capsule export",
        )
        result = apply_project_capsule_export(
            plan,
            authorizations[plan.mutation.plan_id],
        )
        return "applied", {"plan": plan.public_summary(), **result.public_summary()}

    def _import_project_capsule(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"archive_path"})
        plan = prepare_project_capsule_import(
            self._absolute_path_argument(request.arguments, "archive_path"),
            self._store.data_root,
            self._ownership,
        )
        if not request.apply:
            return "planned", {"plan": plan.public_summary(), "applied": False}
        authorizations = self._authorize_effect_plans(
            request,
            plan.plan_id,
            plan.effect_plans,
            "project capsule import",
        )
        result = apply_project_capsule_import(
            plan,
            authorizations,
            self._ownership,
        )
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

    def _evaluate_skill(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(request.arguments, required={"candidate", "evaluation"})
        if request.apply:
            raise ApplicationServiceError("skill evaluation is read-only")
        evaluation = _object_argument(request.arguments, "evaluation")
        expected = {
            "evaluation_id",
            "project_fixture_digest",
            "evaluation_run_digest",
            "evaluator_ref",
            "evaluator_identity_digest",
            "verifier_ref",
            "verifier_identity_digest",
            "tested_model_digest",
            "verifier_model_digest",
            "environment_digest",
            "trial_count",
            "passed_trials",
            "score_basis_points",
            "evaluated_at",
        }
        if set(evaluation) != expected:
            raise ApplicationServiceError("skill evaluation fields are invalid")
        try:
            result = build_skill_evaluation(
                load_skill_lifecycle_policy(self._repo_root),
                parse_skill_candidate(
                    _object_argument(request.arguments, "candidate")
                ),
                **evaluation,
            )
        except (TypeError, ValueError) as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "evaluation": result.as_payload(),
            "registry_mutated": False,
            "grants_authority": False,
        }

    def _plan_skill_change(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        if request.apply:
            raise ApplicationServiceError(
                "skill plan-change prepares a plan and never applies it"
            )
        change_kind = request.arguments.get("change_kind")
        try:
            if change_kind == "activation":
                _check_arguments(
                    request.arguments,
                    required={
                        "change_kind",
                        "candidate",
                        "evaluation",
                        "expected_registry_digest",
                        "rollback_target_ref",
                        "approver_identity_digest",
                    },
                    optional={"supersedes_ref"},
                )
                expected_digest = request.arguments.get(
                    "expected_registry_digest"
                )
                if expected_digest is not None and not isinstance(
                    expected_digest, str
                ):
                    raise ApplicationServiceError(
                        "expected_registry_digest must be a string or null"
                    )
                supersedes = request.arguments.get("supersedes_ref")
                if supersedes is not None and not isinstance(supersedes, str):
                    raise ApplicationServiceError(
                        "supersedes_ref must be a string or null"
                    )
                plan = prepare_skill_activation(
                    self._ownership,
                    load_skill_lifecycle_policy(self._repo_root),
                    parse_skill_candidate(
                        _object_argument(request.arguments, "candidate")
                    ),
                    parse_skill_evaluation(
                        _object_argument(request.arguments, "evaluation")
                    ),
                    expected_registry_digest=expected_digest,
                    rollback_target_ref=_string_argument(
                        request.arguments, "rollback_target_ref"
                    ),
                    approver_identity_digest=_string_argument(
                        request.arguments, "approver_identity_digest"
                    ),
                    supersedes_ref=supersedes,
                )
            elif change_kind == "transition":
                _check_arguments(
                    request.arguments,
                    required={
                        "change_kind",
                        "current",
                        "to_state",
                        "rollback_target_ref",
                        "approver_identity_digest",
                    },
                    optional={"supersedes_ref"},
                )
                supersedes = request.arguments.get("supersedes_ref")
                if supersedes is not None and not isinstance(supersedes, str):
                    raise ApplicationServiceError(
                        "supersedes_ref must be a string or null"
                    )
                plan = prepare_skill_state_change(
                    self._ownership,
                    parse_skill_lifecycle_record(
                        _object_argument(request.arguments, "current")
                    ),
                    to_state=_string_argument(request.arguments, "to_state"),
                    rollback_target_ref=_string_argument(
                        request.arguments, "rollback_target_ref"
                    ),
                    approver_identity_digest=_string_argument(
                        request.arguments, "approver_identity_digest"
                    ),
                    supersedes_ref=supersedes,
                )
            else:
                raise ApplicationServiceError(
                    "change_kind must be activation or transition"
                )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "planned", {
            "plan": plan.as_payload(),
            "expected_plan_id": plan.mutation.plan_id,
            "approval_required": True,
            "registry_mutated": False,
            "grants_authority": False,
        }

    def _memory_context_effectiveness(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        fields = {
            "evaluation_id",
            "required_evidence_refs",
            "recalled_evidence_refs",
            "selected_bytes",
            "used_bytes",
            "selected_tokens",
            "used_tokens",
            "selected_count",
            "stale_selected_count",
            "duplicate_selected_count",
            "omitted_required_count",
            "downstream_success_basis_points",
            "compaction_rehydration_passed",
        }
        _check_arguments(request.arguments, required=fields)
        if request.apply:
            raise ApplicationServiceError(
                "memory context effectiveness is read-only"
            )
        try:
            result = build_context_effectiveness(
                load_memory_hygiene_policy(self._repo_root),
                **dict(request.arguments),
            )
        except (TypeError, ValueError) as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "evaluation": result.as_payload(),
            "memory_mutated": False,
            "grants_authority": False,
        }

    def _memory_hygiene(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        _check_arguments(
            request.arguments,
            required={
                "report_id",
                "as_of",
                "memories",
                "research_evidence",
                "context_evaluations",
            },
        )
        if request.apply:
            raise ApplicationServiceError("memory hygiene is read-only")
        memories = request.arguments.get("memories")
        evidence = request.arguments.get("research_evidence")
        contexts = request.arguments.get("context_evaluations")
        if not all(isinstance(items, list) for items in (memories, evidence, contexts)):
            raise ApplicationServiceError(
                "memory hygiene inputs must be lists"
            )
        try:
            report = build_memory_hygiene_report(
                load_memory_hygiene_policy(self._repo_root),
                [parse_memory_metadata_overlay(item) for item in memories],
                [parse_research_evidence_metadata(item) for item in evidence],
                [parse_context_effectiveness(item) for item in contexts],
                report_id=_identifier_argument(request.arguments, "report_id"),
                as_of=_string_argument(request.arguments, "as_of"),
            )
        except ValueError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        return "ok", {
            "report": report,
            "memory_mutated": False,
            "automatic_actions_performed": False,
            "grants_authority": False,
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

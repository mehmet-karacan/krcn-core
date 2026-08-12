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
from .memory_gate import (
    apply_memory_lifecycle,
    apply_memory_persistence,
    parse_memory_action,
    parse_memory_candidate,
    parse_memory_review,
    prepare_memory_lifecycle,
    prepare_memory_persistence,
)
from .model_routing import load_model_routing_policy, resolve_model_route
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
    apply_work_item,
    prepare_work_item,
    query_work_graph,
    query_work_history,
)


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
    "model.resolve",
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
    "work.item.put",
    "work.query",
    "work.history",
    "runtime.queue.enqueue",
    "runtime.queue.claim",
    "runtime.queue.heartbeat",
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


def _string_tuple_argument(
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
        oracle_metadata_transports: Mapping[str, OracleMetadataTransport] | None = None,
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
            "model.resolve": self._resolve_model,
            "project.learn": self._learn_project,
            "project.integrate": self._integrate_project,
            "project.index-source-code": self._index_source_code,
            "project.search-source-code": self._search_source_code,
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
            "portability.migrate-project-capsules": self._migrate_project_capsules,
            "portability.export-project-capsule": self._export_project_capsule,
            "portability.import-project-capsule": self._import_project_capsule,
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
            "work.item.put": self._put_work_item,
            "work.query": self._query_work,
            "work.history": self._work_history,
            "runtime.queue.enqueue": self._runtime_queue_action,
            "runtime.queue.claim": self._runtime_queue_action,
            "runtime.queue.heartbeat": self._runtime_queue_action,
            "runtime.queue.complete": self._runtime_queue_action,
            "runtime.queue.fail": self._runtime_queue_action,
            "runtime.queue.recover": self._runtime_queue_action,
            "runtime.queue.reconcile": self._runtime_queue_action,
            "runtime.queue.status": self._runtime_queue_status,
            "database.oracle.inspect": self._oracle_inspect,
            "database.oracle.collect": self._oracle_collect,
            "database.oracle.refresh": self._oracle_collect,
            "database.oracle.status": self._oracle_status,
            "database.oracle.index": self._oracle_index,
            "database.oracle.search": self._oracle_search,
            "database.oracle.dependencies": self._oracle_dependencies,
            "retrieval.unified": self._retrieve_unified,
        }
        status, data = handlers[request.operation](request)
        return ServiceResponse(
            request_id=request.request_id,
            operation=request.operation,
            status=status,
            data=data,
        )

    def _put_work_item(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        plan = prepare_work_item(self._store, self._ownership, request.arguments)
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

    def _runtime_queue_action(
        self,
        request: ServiceRequest,
    ) -> tuple[str, Mapping[str, object]]:
        action = request.operation.rsplit(".", 1)[1]
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
        return "ok", build_project_resume_summary(
            self._store,
            match,
            self._repo_root,
        )

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
            source_digest=state.root_digest,
        )
        if source_code_index_is_current(
            self._repo_root,
            self._store.data_root,
            project_id,
            binding.binding_id,
            state.root_digest,
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

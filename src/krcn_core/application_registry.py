"""Explicit application operation-to-handler registry."""

from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Mapping

from .application_contract import APPLICATION_OPERATIONS, ApplicationServiceError


HANDLER_METHODS: Mapping[str, str] = MappingProxyType(
    {
        "installation.inspect": "_inspect_installation",
        "installation.verify": "_verify_installation",
        "release.diff": "_diff_release",
        "release.merge": "_merge_release",
        "deployment.rollback": "_rollback_deployment",
        "project.list": "_list_projects",
        "project.inspect": "_inspect_project",
        "project.resolve-current": "_resolve_current_project",
        "project.resume": "_resume_project",
        "client.bootstrap": "_bootstrap_clients",
        "client.capabilities": "_client_capabilities",
        "client.delegation": "_client_delegation",
        "execution.coordinate": "_coordinate_execution",
        "routing.decide": "_routing_decide",
        "routing.explain": "_routing_explain",
        "routing.record": "_routing_record",
        "result.normalize-native": "_normalize_native_result",
        "result.fan-in": "_fan_in_agent_results",
        "result.trace": "_trace_agent_results",
        "model.resolve": "_resolve_model",
        "model.inventory": "_model_inventory",
        "model.list": "_list_models",
        "model.health": "_model_health",
        "model.health-list": "_list_model_health",
        "model.benchmark-suite": "_model_benchmark_suite",
        "model.benchmark-list": "_list_model_benchmarks",
        "model.benchmark-prepare": "_prepare_model_benchmark_execution",
        "model.benchmark-execute": "_execute_model_benchmark",
        "model.decide": "_decide_model",
        "model.decide-plan": "_decide_task_plan_models",
        "retrieval.evaluate-golden": "_evaluate_retrieval_golden",
        "retrieval.scale-fixture": "_retrieval_scale_fixture",
        "project.learn": "_learn_project",
        "project.integrate": "_integrate_project",
        "project.index-source-code": "_index_source_code",
        "project.search-source-code": "_search_source_code",
        "project.home.resolve": "_resolve_project_home",
        "project.home.initialize": "_initialize_project_home",
        "project.onboard": "_onboard_project",
        "project.rescan": "_rescan_project",
        "project.rebind": "_rebind_project",
        "integration.select-read-only": "_select_read_only_integration",
        "portability.backup": "_portable_backup",
        "portability.restore": "_portable_restore",
        "portability.migrate-repo-local": "_migrate_repo_local",
        "portability.migrate-project-home": "_migrate_project_home",
        "portability.restore-project-home": "_restore_project_home",
        "portability.merge-project-home": "_merge_project_home",
        "portability.migrate-project-capsules": "_migrate_project_capsules",
        "portability.export-project-capsule": "_export_project_capsule",
        "portability.import-project-capsule": "_import_project_capsule",
        "knowledge.catalog": "_knowledge_catalog",
        "knowledge.search-exact": "_search_exact",
        "knowledge.search-dependencies": "_search_dependencies",
        "knowledge.search-semantic": "_search_semantic",
        "knowledge.index-hybrid": "_index_hybrid",
        "knowledge.search-hybrid": "_search_hybrid",
        "context.build": "_build_context",
        "memory.propose": "_propose_memory",
        "memory.review": "_review_memory",
        "memory.persist": "_persist_memory",
        "memory.lifecycle": "_change_memory_lifecycle",
        "memory.hygiene": "_memory_hygiene",
        "memory.context-effectiveness": "_memory_context_effectiveness",
        "skill.evaluate": "_evaluate_skill",
        "skill.plan-change": "_plan_skill_change",
        "autonomy.status": "_autonomy_status",
        "autonomy.morning": "_autonomy_morning",
        "autonomy.admission": "_autonomy_admission",
        "work.item.put": "_put_work_item",
        "work.list": "_list_work",
        "work.import": "_import_work",
        "work.documents.copy-initial": "_copy_initial_work_documents",
        "work.documents.migrate-layout": "_migrate_work_document_layout",
        "work.documents.process": "_process_work_documents",
        "work.index-readable": "_index_work_readable",
        "work.index-semantic": "_index_work_semantic",
        "work.search": "_search_work",
        "work.query": "_query_work",
        "work.history": "_work_history",
        "research.prepare": "_prepare_research",
        "research.action": "_research_action",
        "research.import-response": "_import_research_response",
        "research.status": "_research_status",
        "research.availability": "_research_availability",
        "research.dispatch": "_research_dispatch",
        "research.cancel": "_research_cancel",
        "research.runtime-status": "_research_runtime_status",
        "research.resume": "_research_resume",
        "runtime.queue.enqueue": "_runtime_queue_action",
        "runtime.queue.migrate-v2": "_runtime_queue_action",
        "runtime.queue.claim": "_runtime_queue_action",
        "runtime.queue.heartbeat": "_runtime_queue_action",
        "runtime.queue.bind-effect-claim": "_runtime_queue_action",
        "runtime.queue.bind-effect-receipt": "_runtime_queue_action",
        "runtime.queue.complete": "_runtime_queue_action",
        "runtime.queue.fail": "_runtime_queue_action",
        "runtime.queue.recover": "_runtime_queue_action",
        "runtime.queue.reconcile": "_runtime_queue_action",
        "runtime.queue.status": "_runtime_queue_status",
        "database.oracle.inspect": "_oracle_inspect",
        "database.oracle.collect": "_oracle_collect",
        "database.oracle.refresh": "_oracle_collect",
        "database.oracle.status": "_oracle_status",
        "database.oracle.index": "_oracle_index",
        "database.oracle.search": "_oracle_search",
        "database.oracle.dependencies": "_oracle_dependencies",
        "retrieval.unified": "_retrieve_unified",
    }
)


def bind_application_handlers(
    service: object,
) -> dict[str, Callable[..., object]]:
    """Bind the explicit registry without module scanning or fallback routes."""

    if set(HANDLER_METHODS) != set(APPLICATION_OPERATIONS):
        raise ApplicationServiceError("application handler registry is incomplete")
    handlers: dict[str, Callable[..., object]] = {}
    for operation, method_name in HANDLER_METHODS.items():
        handler = getattr(service, method_name, None)
        if not callable(handler):
            raise ApplicationServiceError(
                f"application handler is unavailable: {operation}"
            )
        handlers[operation] = handler
    return handlers

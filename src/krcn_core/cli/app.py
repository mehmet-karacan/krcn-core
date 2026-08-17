"""Safe KRCN Core CLI baseline."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Mapping

from krcn_core.application import create_application_service
from krcn_core.application_contract import (
    ApplicationServiceError,
    ServiceRequest,
    ServiceResponse,
)
from krcn_core.doctor import run_doctor
from krcn_core.intent_routing import (
    project_learning_route,
    route_project_request,
)
from krcn_core.project_home import (
    PROJECT_HOME_DIRECTORY,
    PROJECT_HOME_MANIFEST,
    discover_initialized_project_home,
)
from krcn_core.project_learning_intent import parse_project_learning_intent
from krcn_core.research_intent import ResearchIntentError, parse_research_intent
from krcn_core.project_navigation import (
    ProjectNavigationError,
    parse_project_navigation_intent,
)
from krcn_core.model_health import OpenAICompatibleModelHealthProbe
from krcn_core.secret_provider import OpenCodeSecretProvider
from krcn_core.repository_context import main as context_main
from krcn_core.user_home import resolve_user_home
from krcn_core.work_intent import (
    WorkIntentError,
    parse_work_create_intent,
    parse_work_document_intent,
)

from .registry import compatibility_registry
from .renderers.service_response import render_service_response
from .renderers.table import (
    display_status as _display_status,
    display_timestamp as _display_timestamp,
    shorten as _shorten,
    text_table as _text_table,
    work_count_pair as _work_count_pair,
)


KRCN_CORE_HOME_ENV = "KRCN_CORE_HOME"


def _is_krcn_core_root(candidate: Path) -> bool:
    manifest = candidate / ".ai" / "repository-context.json"
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    project = payload.get("project")
    return isinstance(project, dict) and project.get("id") == "krcn-core"


def discover_repo_root(
    start: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Find the KRCN Core repository from the working tree or user setup."""

    candidate = (start or Path.cwd()).resolve()
    for directory in (candidate, *candidate.parents):
        if _is_krcn_core_root(directory):
            return directory

    environment = os.environ if environ is None else environ
    configured = environment.get(KRCN_CORE_HOME_ENV)
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            raise ValueError(f"{KRCN_CORE_HOME_ENV} must be an absolute path")
        configured_root = configured_path.resolve(strict=False)
        if _is_krcn_core_root(configured_root):
            return configured_root
        raise ValueError(
            f"{KRCN_CORE_HOME_ENV} does not point to a KRCN Core repository"
        )
    raise ValueError(
        "KRCN Core repository was not found; run the CLI installer or pass --repo"
    )


def _print_error(exc: Exception) -> None:
    message = str(exc)
    normalized = message.casefold()
    if "hybrid index" in normalized:
        guidance = "Build or rebuild it with `krcn knowledge index` and the returned exact plan id."
    elif "secret" in normalized:
        guidance = "Configure the referenced value in the active local secret provider, then retry."
    elif "approval" in normalized or "exact plan" in normalized:
        guidance = "Run the command without `--apply`, review its plan, then apply that exact plan with the requested approval."
    elif "not found" in normalized or "was not found" in normalized:
        guidance = "Check the active project home and inspect the registered project or task identifiers."
    elif "choice" in normalized or "project-home" in normalized:
        guidance = "Choose the default project `.krcn` home or provide an explicit local parent directory."
    else:
        guidance = "Run `krcn doctor` for local health checks and review the command help."
    print(f"ERROR: {message}", file=sys.stderr)
    print(f"NEXT: {guidance}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="krcn", description="KRCN Core CLI")
    subparsers = parser.add_subparsers(dest="command")
    catalog = subparsers.add_parser(
        "catalog",
        help="List reviewed legacy command contracts without executing them",
    )
    catalog.add_argument("--include-internal", action="store_true")
    catalog.add_argument("--format", choices=("text", "json"), default="text")
    context = subparsers.add_parser(
        "context",
        help="Resolve the shared repository context",
    )
    context.add_argument("--repo", type=Path)
    context.add_argument("--format", choices=("text", "json"), default="text")
    context.add_argument("--validate-only", action="store_true")
    for command_name in ("doctor", "validate"):
        doctor = subparsers.add_parser(
            command_name,
            help="Run offline repository health checks",
        )
        doctor.add_argument("--repo", type=Path)
        doctor.add_argument("--data-root", type=Path)
        doctor.add_argument("--format", choices=("text", "json"), default="text")
    ask = subparsers.add_parser(
        "ask",
        help="Route a natural-language request through shared services",
    )
    ask.add_argument("request")
    ask.add_argument("--source", type=Path)
    ask.add_argument(
        "--context",
        help="Supply the current conversational subject for references such as 'bunu'",
    )
    _add_service_options(ask, mutation=True)
    ask.set_defaults(format=None)
    _add_project_home_choice_options(ask)
    project = subparsers.add_parser(
        "project",
        help="Manage local project registrations through shared services",
    )
    project_commands = project.add_subparsers(dest="project_command")
    project_list = project_commands.add_parser(
        "list",
        help="List registered projects without exposing source locations",
    )
    _add_service_options(project_list)
    project_list.set_defaults(format="text")
    project_inspect = project_commands.add_parser(
        "inspect",
        help="Inspect a registered project with redacted source bindings",
    )
    project_inspect.add_argument("project_id")
    _add_service_options(project_inspect)
    for command_name in ("current", "resume"):
        project_context = project_commands.add_parser(
            command_name,
            help=(
                "Resolve the registered project for the current task"
                if command_name == "current"
                else "Return the safe cross-client project resume summary"
            ),
        )
        project_context.add_argument("--directory", type=Path)
        project_context.add_argument("--project")
        project_context.add_argument("--request")
        _add_service_options(project_context)
    project_learn = project_commands.add_parser(
        "learn",
        help="Learn a local project from only its directory",
    )
    project_learn.add_argument("source", type=Path)
    _add_service_options(project_learn, mutation=True)
    _add_project_home_choice_options(project_learn)
    project_integrate = project_commands.add_parser(
        "integrate",
        help="Complete or refresh every project integration stage",
    )
    project_integrate_target = project_integrate.add_mutually_exclusive_group(
        required=True
    )
    project_integrate_target.add_argument("--source", type=Path)
    project_integrate_target.add_argument("--project")
    project_integrate.add_argument(
        "--scan-mode",
        choices=("manual", "automatic"),
        default="manual",
    )
    _add_service_options(project_integrate, mutation=True)
    project_index_code = project_commands.add_parser(
        "index-code",
        help="Plan or build the contentless source-code vector index",
    )
    project_index_code.add_argument("project_id")
    _add_service_options(project_index_code, mutation=True)
    project_search_code = project_commands.add_parser(
        "search-code",
        help="Search indexed project code and read verified hits in place",
    )
    project_search_code.add_argument("project_id")
    project_search_code.add_argument("query")
    project_search_code.add_argument("--language", action="append", default=[])
    project_search_code.add_argument("--path-prefix")
    project_search_code.add_argument("--limit", type=int, default=10)
    project_search_code.add_argument("--metadata-only", action="store_true")
    _add_service_options(project_search_code)
    project_search_code.add_argument("--approval-id")
    project_onboard = project_commands.add_parser(
        "onboard",
        help="Plan or apply read-only local project onboarding",
    )
    project_onboard.add_argument("--workspace-id", required=True)
    project_onboard.add_argument("--project-id", required=True)
    project_onboard.add_argument("--binding-id", required=True)
    project_onboard.add_argument("--name", required=True)
    project_onboard.add_argument("--description", default="")
    project_onboard.add_argument("--source", type=Path, required=True)
    project_onboard.add_argument("--policy-ref", action="append", default=[])
    project_onboard.add_argument("--expected-workspace-revision", type=int, default=0)
    _add_service_options(project_onboard, mutation=True)
    project_rescan = project_commands.add_parser(
        "rescan",
        help="Plan or apply read-only project rescan",
    )
    project_rescan.add_argument("project_id")
    project_rescan.add_argument("--binding-id")
    _add_service_options(project_rescan, mutation=True)
    project_rebind = project_commands.add_parser(
        "rebind",
        help="Plan or apply verified relocation of an external project",
    )
    project_rebind.add_argument("project_id")
    project_rebind.add_argument("--binding-id")
    project_rebind.add_argument("--source", type=Path, required=True)
    _add_service_options(project_rebind, mutation=True)
    integration = subparsers.add_parser(
        "integration",
        help="Use registered local integrations through shared policy gates",
    )
    integration_commands = integration.add_subparsers(dest="integration_command")
    integration_select = integration_commands.add_parser(
        "select",
        help="Run one policy-approved read-only database statement",
    )
    integration_select.add_argument("--integration-id", required=True)
    integration_select.add_argument("--binding-id", required=True)
    integration_select.add_argument("--statement", required=True)
    integration_select.add_argument("--maximum-rows", type=int, default=1_000)
    _add_service_options(integration_select)
    oracle = subparsers.add_parser(
        "oracle",
        help="Use project-scoped Oracle schema metadata without reading rows",
    )
    oracle_commands = oracle.add_subparsers(dest="oracle_command")
    for operation in ("collect", "refresh", "index"):
        command = oracle_commands.add_parser(
            operation,
            help=f"Plan or apply Oracle metadata {operation}",
        )
        _add_phase_four_options(command, mutation=True)
    for operation in ("inspect", "status", "search", "dependencies"):
        command = oracle_commands.add_parser(
            operation,
            help=f"Read Oracle metadata {operation} from a JSON request",
        )
        _add_phase_four_options(command)
    retrieval = subparsers.add_parser(
        "retrieval",
        help="Use evidence-first retrieval across registered project domains",
    )
    retrieval_commands = retrieval.add_subparsers(dest="retrieval_command")
    unified = retrieval_commands.add_parser(
        "unified",
        help="Run one project-scoped unified retrieval request",
    )
    _add_phase_four_options(unified)
    installation = subparsers.add_parser(
        "installation",
        help="Inspect or verify a local KRCN Core installation",
    )
    installation_commands = installation.add_subparsers(
        dest="installation_command"
    )
    for operation in ("inspect", "verify"):
        command = installation_commands.add_parser(
            operation,
            help=f"{operation.capitalize()} a local installation without mutation",
        )
        _add_installation_options(command)
    release = subparsers.add_parser(
        "release",
        help="Diff or merge a trusted local release package",
    )
    release_commands = release.add_subparsers(dest="release_command")
    release_diff = release_commands.add_parser(
        "diff",
        help="Compare a trusted release without mutation",
    )
    _add_release_options(release_diff)
    release_merge = release_commands.add_parser(
        "merge",
        help="Plan or apply a trusted release merge",
    )
    _add_release_options(release_merge, mutation=True)
    deployment = subparsers.add_parser(
        "deployment",
        help="Manage recoverable local deployments",
    )
    deployment_commands = deployment.add_subparsers(dest="deployment_command")
    rollback = deployment_commands.add_parser(
        "rollback",
        help="Plan or apply an exact checkpoint rollback",
    )
    rollback.add_argument("deployment_id")
    _add_installation_options(rollback, mutation=True)
    knowledge = subparsers.add_parser(
        "knowledge",
        help="Use the shared local knowledge catalog and retrieval services",
    )
    knowledge_commands = knowledge.add_subparsers(dest="knowledge_command")
    knowledge_catalog = knowledge_commands.add_parser(
        "catalog",
        help="List revision-aware catalog entries without source locations",
    )
    _add_phase_four_options(knowledge_catalog, request_required=False)
    for operation in ("exact", "dependencies"):
        command = knowledge_commands.add_parser(
            operation,
            help=f"Run shared {operation} retrieval from a JSON request",
        )
        _add_phase_four_options(command)
    semantic = knowledge_commands.add_parser(
        "semantic",
        help="Run provider-gated semantic retrieval from a JSON request",
    )
    _add_phase_four_options(semantic, approval=True)
    hybrid_index = knowledge_commands.add_parser(
        "index",
        help="Plan or build the local SQLite hybrid retrieval index",
    )
    _add_service_options(hybrid_index, mutation=True)
    hybrid = knowledge_commands.add_parser(
        "hybrid",
        help="Run explainable local hybrid retrieval from a JSON request",
    )
    _add_phase_four_options(hybrid)
    context_package = subparsers.add_parser(
        "context-package",
        help="Build an evidence-bounded context package",
    )
    context_commands = context_package.add_subparsers(dest="context_package_command")
    context_build = context_commands.add_parser(
        "build",
        help="Build context through the shared service from a JSON request",
    )
    _add_phase_four_options(context_build)
    memory = subparsers.add_parser(
        "memory",
        help="Use the shared Memory Gate services",
    )
    memory_commands = memory.add_subparsers(dest="memory_command")
    for operation in ("propose", "review"):
        command = memory_commands.add_parser(
            operation,
            help=f"Run shared memory {operation} validation from a JSON request",
        )
        _add_phase_four_options(command)
    for operation in ("persist", "lifecycle"):
        command = memory_commands.add_parser(
            operation,
            help=f"Plan or apply shared memory {operation} from a JSON request",
        )
        _add_phase_four_options(command, mutation=True)
    for operation, help_text in (
        (
            "hygiene",
            "Measure stale, conflicting, duplicate, unused, and retention metadata",
        ),
        (
            "context-effectiveness",
            "Measure evidence recall, context use, and downstream effectiveness",
        ),
    ):
        command = memory_commands.add_parser(operation, help=help_text)
        _add_phase_four_options(command)
        command.set_defaults(format="text")
    autonomy = subparsers.add_parser(
        "autonomy",
        help="Inspect bounded measured-loop state without granting authority",
    )
    autonomy_commands = autonomy.add_subparsers(dest="autonomy_command")
    for operation, help_text in (
        ("status", "Validate a measured-loop chain and calculate its state"),
        ("morning", "Build a prompt-free morning digest from a valid status"),
        ("admission", "Calculate adaptive claim admission from bounded pressure data"),
    ):
        command = autonomy_commands.add_parser(operation, help=help_text)
        _add_phase_four_options(command)
        command.set_defaults(format="text")
    routing = subparsers.add_parser(
        "routing",
        help="Inspect authority-free adaptive routing shadow decisions",
    )
    routing_commands = routing.add_subparsers(dest="routing_command")
    for operation, help_text in (
        ("decide", "Calculate a deterministic shadow route decision"),
        ("explain", "Compare a shadow decision with the observed coordinator route"),
        ("record", "Persist one append-only shadow route decision"),
    ):
        command = routing_commands.add_parser(operation, help=help_text)
        _add_phase_four_options(command, mutation=operation == "record")
        command.set_defaults(format="text")
    outbound = subparsers.add_parser(
        "outbound",
        help="Assess one exact provider payload disclosure without sending data",
    )
    outbound_commands = outbound.add_subparsers(dest="outbound_command")
    outbound_assess = outbound_commands.add_parser(
        "assess",
        help="Evaluate an outbound ProviderRequest and assurance profile",
    )
    _add_phase_four_options(outbound_assess)
    outbound_assess.set_defaults(format="text")
    sandbox = subparsers.add_parser(
        "sandbox",
        help="Plan an exact detached worktree sandbox without creating it",
    )
    sandbox_commands = sandbox.add_subparsers(dest="sandbox_command")
    sandbox_plan = sandbox_commands.add_parser(
        "plan",
        help="Build an authority-free worktree sandbox plan",
    )
    _add_phase_four_options(sandbox_plan)
    sandbox_plan.set_defaults(format="text")
    result = subparsers.add_parser(
        "result",
        help="Normalize and aggregate authority-free agent results",
    )
    result_commands = result.add_subparsers(dest="result_command")
    for operation, help_text in (
        ("normalize-native", "Normalize one structured native client result"),
        ("fan-in", "Build one coordinator-only bounded fan-in summary"),
        ("trace", "Aggregate workflow receipts into an execution trace"),
    ):
        command = result_commands.add_parser(operation, help=help_text)
        _add_phase_four_options(command)
        command.set_defaults(format="text")
    skills = subparsers.add_parser(
        "skills",
        help="Evaluate skill candidates and prepare reviewed registry changes",
    )
    skill_commands = skills.add_subparsers(dest="skills_command")
    skill_evaluate = skill_commands.add_parser(
        "evaluate",
        help="Evaluate one candidate with independent verifier evidence",
    )
    _add_phase_four_options(skill_evaluate)
    skill_evaluate.set_defaults(format="text")
    skill_plan = skill_commands.add_parser(
        "plan-change",
        help="Prepare but never apply an exact skill registry change",
    )
    _add_phase_four_options(skill_plan)
    skill_plan.set_defaults(format="text")
    models = subparsers.add_parser(
        "models",
        help="Use measured model benchmark execution contracts",
    )
    models_commands = models.add_subparsers(dest="models_command")
    benchmark = models_commands.add_parser(
        "benchmark",
        help="Prepare or execute repeated benchmark trials",
    )
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command")
    benchmark_prepare = benchmark_commands.add_parser(
        "prepare",
        help="Prepare an exact repeated-trial benchmark plan",
    )
    _add_phase_four_options(benchmark_prepare, approval=True)
    benchmark_prepare.set_defaults(format="text")
    benchmark_execute = benchmark_commands.add_parser(
        "execute",
        help="Execute only through an explicitly injected host adapter",
    )
    _add_phase_four_options(benchmark_execute, mutation=True)
    benchmark_execute.set_defaults(format="text")
    work = subparsers.add_parser(
        "work",
        help="Use the authoritative project Work Graph",
    )
    work_commands = work.add_subparsers(dest="work_command")
    work_list = work_commands.add_parser(
        "list",
        help="List project tasks, requests, or defects as a readable table",
    )
    work_list.add_argument("--project")
    work_list.add_argument(
        "--type",
        dest="work_type",
        choices=("request", "defect", "task"),
    )
    work_list.add_argument(
        "--status",
        dest="lifecycle",
        choices=("active", "historical", "all"),
        default="all",
    )
    work_list.add_argument("--limit", type=int, default=100)
    _add_service_options(work_list)
    work_list.set_defaults(format="text")
    work_put = work_commands.add_parser(
        "put",
        help="Plan or apply one exact project work item revision",
    )
    _add_phase_four_options(work_put, mutation=True)
    work_import = work_commands.add_parser(
        "import",
        help="Plan or apply one project-scoped legacy work batch",
    )
    work_import.add_argument("--source-root", type=Path, required=True)
    _add_phase_four_options(work_import, mutation=True)
    work_copy_documents = work_commands.add_parser(
        "copy-documents-initial",
        help="Copy initial request, defect, and task documents into project-local data",
    )
    work_copy_documents.add_argument("project_id")
    work_copy_documents.add_argument("--db-scripts-root", type=Path, required=True)
    work_copy_documents.add_argument("--legacy-root", type=Path, required=True)
    _add_service_options(work_copy_documents, mutation=True)
    work_migrate_document_layout = work_commands.add_parser(
        "migrate-document-layout",
        help="Plan or apply the project work-document layout migration",
    )
    work_migrate_document_layout.add_argument("project_id")
    work_migrate_document_layout.add_argument(
        "--identity-decision",
        action="append",
        default=[],
        metavar="KEY=request|defect|exclude",
        help=(
            "Review one ambiguous identity as a request or explicitly exclude it; "
            "repeat for multiple identities"
        ),
    )
    _add_service_options(work_migrate_document_layout, mutation=True)
    work_process_documents = work_commands.add_parser(
        "process-documents",
        help="Update Work Graph and semantic retrieval from project-local documents",
    )
    work_process_documents.add_argument("project_id")
    _add_service_options(work_process_documents, mutation=True)
    work_index_semantic = work_commands.add_parser(
        "index-semantic",
        help="Plan or build the local project work semantic index",
    )
    _add_phase_four_options(work_index_semantic, mutation=True)
    work_index_readable = work_commands.add_parser(
        "index-readable",
        help="Plan or build the readable project WORK-INDEX projection",
    )
    work_index_readable.add_argument("project_id")
    _add_service_options(work_index_readable, mutation=True)
    work_index_readable.set_defaults(format="text")
    work_search = work_commands.add_parser(
        "search",
        help="Run exact, lexical, graph, and semantic work retrieval",
    )
    _add_phase_four_options(work_search)
    for operation in ("query", "history"):
        command = work_commands.add_parser(
            operation,
            help=f"Read authoritative work {operation} from a JSON request",
        )
        _add_phase_four_options(command)
    research = subparsers.add_parser(
        "research",
        help="Prepare, import, and inspect project research artifacts",
    )
    research_commands = research.add_subparsers(dest="research_command")
    for operation in ("prepare", "import-response", "dispatch", "cancel"):
        command = research_commands.add_parser(
            operation,
            help=f"Plan or apply research {operation} from a JSON request",
        )
        _add_phase_four_options(command, mutation=True)
    research_status = research_commands.add_parser(
        "status",
        help="Read research status from a JSON request",
    )
    _add_phase_four_options(research_status)
    for operation in ("availability", "runtime-status", "resume"):
        command = research_commands.add_parser(
            operation,
            help=f"Read research {operation} from a JSON request",
        )
        _add_phase_four_options(command)
    runtime = subparsers.add_parser(
        "runtime",
        help="Use the project-scoped agent queue and lease runtime",
    )
    runtime_commands = runtime.add_subparsers(dest="runtime_command")
    for operation in (
        "enqueue", "migrate-v2", "claim", "heartbeat", "bind-effect-claim",
        "bind-effect-receipt", "complete", "fail", "recover", "reconcile",
    ):
        command = runtime_commands.add_parser(
            operation,
            help=f"Plan or apply runtime queue {operation}",
        )
        _add_phase_four_options(command, mutation=True)
    runtime_status = runtime_commands.add_parser(
        "status",
        help="Read runtime queue status from a JSON request",
    )
    _add_phase_four_options(runtime_status)
    orchestrator = subparsers.add_parser(
        "orchestrator",
        help="Use the shared client-neutral orchestration service",
    )
    orchestrator_commands = orchestrator.add_subparsers(
        dest="orchestrator_command"
    )
    for operation in (
        "intent",
        "plan",
        "authorize",
        "start",
        "execute",
        "verify",
        "status",
        "timeline",
        "resume",
    ):
        command = orchestrator_commands.add_parser(
            operation,
            help=f"Run shared orchestrator {operation} from a JSON request",
        )
        command.add_argument("--repo", type=Path)
        command.add_argument("--data-root", type=Path)
        command.add_argument("--request-file", type=Path, required=True)
        command.add_argument("--format", choices=("text", "json"), default="json")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--expected-plan")
    portability = subparsers.add_parser(
        "portability",
        help="Back up and restore the portable KRCN user home",
    )
    portability_commands = portability.add_subparsers(dest="portability_command")
    backup = portability_commands.add_parser(
        "backup",
        help="Plan or create a secret-safe portable backup",
    )
    backup.add_argument("--output", type=Path, required=True)
    _add_service_options(backup, mutation=True)
    restore = portability_commands.add_parser(
        "restore",
        help="Plan or restore a portable backup into an empty user home",
    )
    restore.add_argument("--input", type=Path, required=True)
    _add_service_options(restore, mutation=True)
    migrate = portability_commands.add_parser(
        "migrate-repo-local",
        help="Plan or migrate repository-local .krcn into the portable user home",
    )
    migrate.add_argument("--backup-output", type=Path, required=True)
    _add_service_options(migrate, mutation=True)
    project_migrate = portability_commands.add_parser(
        "migrate-project-home",
        help="Migrate one existing home into an approved project-scoped home",
    )
    project_migrate.add_argument("--source-home", type=Path, required=True)
    project_migrate.add_argument("--project", type=Path, required=True)
    project_migrate.add_argument("--backup-output", type=Path, required=True)
    project_migrate.add_argument(
        "--home-choice",
        choices=("use-default", "choose-parent"),
        required=True,
    )
    project_migrate.add_argument("--home-parent", type=Path)
    _add_service_options(project_migrate, mutation=True)
    project_restore = portability_commands.add_parser(
        "restore-project-home",
        help="Restore a project-home backup into a clean project clone",
    )
    project_restore.add_argument("--input", type=Path, required=True)
    project_restore.add_argument("--project", type=Path, required=True)
    project_restore.add_argument(
        "--home-choice",
        choices=("use-default", "choose-parent"),
        required=True,
    )
    project_restore.add_argument("--home-parent", type=Path)
    _add_service_options(project_restore, mutation=True)
    project_merge = portability_commands.add_parser(
        "merge-project-home",
        help="Merge project records into an existing shared user home",
    )
    project_merge.add_argument("--source-home", type=Path, required=True)
    project_merge.add_argument("--target-home", type=Path, required=True)
    project_merge.add_argument("--backup-directory", type=Path, required=True)
    _add_service_options(project_merge, mutation=True)
    capsule_migrate = portability_commands.add_parser(
        "migrate-project-capsules",
        help="Migrate a flat KRCN home into project capsules",
    )
    capsule_migrate.add_argument("--backup-output", type=Path, required=True)
    _add_service_options(capsule_migrate, mutation=True)
    capsule_export = portability_commands.add_parser(
        "export-project-capsule",
        help="Export one sanitized thin or ready project capsule",
    )
    capsule_export.add_argument("project_id")
    capsule_export.add_argument("--output", type=Path, required=True)
    capsule_export.add_argument(
        "--mode",
        choices=("thin", "ready"),
        default="thin",
    )
    _add_service_options(capsule_export, mutation=True)
    capsule_import = portability_commands.add_parser(
        "import-project-capsule",
        help="Import one sanitized project capsule into a layout v2 home",
    )
    capsule_import.add_argument("--input", type=Path, required=True)
    _add_service_options(capsule_import, mutation=True)
    client = subparsers.add_parser(
        "client",
        help="Manage user-level AI client bootstrap guidance",
    )
    client_commands = client.add_subparsers(dest="client_command")
    client_bootstrap = client_commands.add_parser(
        "bootstrap",
        help="Plan or install managed KRCN guidance for supported AI clients",
    )
    _add_service_options(client_bootstrap, mutation=True)
    for command_name, help_text in (
        (
            "capabilities",
            "Validate the current AI client session capability declaration",
        ),
        (
            "delegation",
            "Classify project work and select a safe multi-agent execution mode",
        ),
    ):
        command = client_commands.add_parser(command_name, help=help_text)
        command.add_argument("--session-id", required=True)
        command.add_argument("--client-id", required=True)
        command.add_argument(
            "--native-subagents",
            action="store_true",
            help=(
                "Declare native subagent lifecycle and attributed terminal "
                "result support"
            ),
        )
        command.add_argument(
            "--parallel-subagents",
            action="store_true",
            help="Declare concurrent native subagent execution support",
        )
        command.add_argument("--per-agent-model-selection", action="store_true")
        command.add_argument("--agent-cancellation", action="store_true")
        command.add_argument(
            "--structured-results",
            action="store_true",
            help="Declare machine-validatable delegated result payloads",
        )
        command.add_argument("--isolated-role-execution", action="store_true")
        command.add_argument(
            "--max-parallel-agents",
            type=int,
            help=(
                "Declare the available agent slots; defaults to 2 for native "
                "parallel clients and 1 otherwise"
            ),
        )
        if command_name == "delegation":
            command.add_argument(
                "--work-class",
                required=True,
                help="Reviewed work class from the delegation policy",
            )
            project_match = command.add_mutually_exclusive_group(required=True)
            project_match.add_argument(
                "--project-matched",
                dest="project_matched",
                action="store_true",
            )
            project_match.add_argument(
                "--project-unmatched",
                dest="project_matched",
                action="store_false",
            )
        _add_service_options(command)
    model = subparsers.add_parser(
        "model",
        help="Resolve client-neutral model profiles without granting authority",
    )
    model_commands = model.add_subparsers(dest="model_command")
    model_resolve = model_commands.add_parser(
        "resolve",
        help="Resolve one role or workload to an available model or safe fallback",
    )
    selector = model_resolve.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--role",
        choices=("planner", "worker", "verifier"),
    )
    selector.add_argument(
        "--workload",
        choices=(
            "general",
            "planning",
            "implementation",
            "verification",
            "discovery",
            "embedding",
        ),
    )
    model_resolve.add_argument(
        "--bind",
        action="append",
        default=[],
        metavar="CANDIDATE=MODEL",
    )
    model_resolve.add_argument(
        "--authorize",
        action="append",
        default=[],
        metavar="CANDIDATE",
    )
    _add_service_options(model_resolve)
    model_inventory = model_commands.add_parser(
        "inventory",
        help="Plan or apply a credential-free global model inventory",
    )
    model_inventory.add_argument("--input", type=Path, required=True)
    _add_service_options(model_inventory, mutation=True)
    model_list = model_commands.add_parser(
        "list",
        help="List registered models without credentials or endpoints",
    )
    _add_service_options(model_list)
    model_health = model_commands.add_parser(
        "health",
        help="Run one approved synthetic model health probe",
    )
    model_health.add_argument("model_ref")
    model_health.add_argument("--endpoint", required=True)
    model_health.add_argument(
        "--retention-assumptions",
        required=True,
    )
    model_health.add_argument("--session-id", required=True)
    model_health.add_argument(
        "--opencode-config",
        type=Path,
        default=Path.home() / ".config" / "opencode" / "opencode.json",
    )
    model_health.add_argument(
        "--credential-reference",
        default="opencode://litellm/api-key",
    )
    model_health.add_argument("--force-retest", action="store_true")
    _add_service_options(model_health, mutation=True)
    model_health_list = model_commands.add_parser(
        "health-list",
        help="List sanitized model health and quarantine states",
    )
    _add_service_options(model_health_list)
    model_benchmark_suite = model_commands.add_parser(
        "benchmark-suite",
        help="Plan or build one project-specific safe micro benchmark suite",
    )
    model_benchmark_suite.add_argument("project_id")
    _add_service_options(model_benchmark_suite, mutation=True)
    model_benchmark_list = model_commands.add_parser(
        "benchmark-list",
        help="List project micro benchmark suite summaries",
    )
    model_benchmark_list.add_argument("--project")
    _add_service_options(model_benchmark_list)
    return parser


def _add_service_options(
    parser: argparse.ArgumentParser,
    *,
    mutation: bool = False,
) -> None:
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="json")
    if mutation:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-plan")
        parser.add_argument("--approval-id")


def _add_project_home_choice_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--home-choice",
        choices=("use-default", "choose-parent", "cancel"),
    )
    parser.add_argument("--home-parent", type=Path)


def _add_installation_options(
    parser: argparse.ArgumentParser,
    *,
    mutation: bool = False,
) -> None:
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--format", choices=("text", "json"), default="json")
    if mutation:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-plan")
        parser.add_argument("--approval-id")


def _add_release_options(
    parser: argparse.ArgumentParser,
    *,
    mutation: bool = False,
) -> None:
    _add_installation_options(parser, mutation=mutation)
    parser.add_argument("--release", dest="release_path", type=Path, required=True)
    parser.add_argument("--trusted-manifest-sha256", required=True)


def _add_phase_four_options(
    parser: argparse.ArgumentParser,
    *,
    request_required: bool = True,
    mutation: bool = False,
    approval: bool = False,
) -> None:
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--data-root", type=Path)
    if request_required:
        parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--format", choices=("text", "json"), default="json")
    if mutation:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-plan")
    if mutation or approval:
        parser.add_argument("--approval-id")


def _project_service_request(args: argparse.Namespace) -> ServiceRequest:
    if args.project_command == "list":
        operation = "project.list"
        arguments: dict[str, object] = {}
    elif args.project_command == "inspect":
        operation = "project.inspect"
        arguments = {"project_id": args.project_id}
    elif args.project_command in {"current", "resume"}:
        operation = (
            "project.resolve-current"
            if args.project_command == "current"
            else "project.resume"
        )
        arguments = {
            "working_directory": str(
                (args.directory if args.directory is not None else Path.cwd()).resolve()
            )
        }
        if args.project is not None:
            arguments["project_ref"] = args.project
        if args.request is not None:
            arguments["request_text"] = args.request
    elif args.project_command == "learn":
        operation = "project.learn"
        arguments = {
            "request_text": str(args.source.resolve()),
            "source_root": str(args.source.resolve()),
        }
    elif args.project_command == "integrate":
        operation = "project.integrate"
        arguments = {"scan_mode": args.scan_mode}
        if args.source is not None:
            arguments["source_root"] = str(args.source.resolve())
        else:
            arguments["project_id"] = args.project
    elif args.project_command == "index-code":
        operation = "project.index-source-code"
        arguments = {"project_id": args.project_id}
    elif args.project_command == "search-code":
        operation = "project.search-source-code"
        arguments = {
            "query": {
                "schema_ref": "schemas/source-code-query.schema.json",
                "schema_version": 1,
                "query_id": "cli-source-code-query",
                "project_id": args.project_id,
                "text": args.query,
                "languages": args.language,
                "path_prefix": args.path_prefix,
                "include_content": not args.metadata_only,
                "limit": args.limit,
            }
        }
    elif args.project_command == "onboard":
        operation = "project.onboard"
        arguments = {
            "workspace_id": args.workspace_id,
            "project_id": args.project_id,
            "binding_id": args.binding_id,
            "project_name": args.name,
            "description": args.description,
            "source_root": str(args.source.resolve()),
            "policy_refs": args.policy_ref,
            "expected_workspace_revision": args.expected_workspace_revision,
        }
    elif args.project_command == "rescan":
        operation = "project.rescan"
        arguments = {"project_id": args.project_id}
        if args.binding_id:
            arguments["binding_id"] = args.binding_id
    elif args.project_command == "rebind":
        operation = "project.rebind"
        arguments = {
            "project_id": args.project_id,
            "candidate_root": str(args.source.resolve()),
        }
        if args.binding_id:
            arguments["binding_id"] = args.binding_id
    else:
        raise ApplicationServiceError("project command is required")
    return ServiceRequest(
        client_kind="cli",
        operation=operation,
        arguments=arguments,
        apply=getattr(args, "apply", False),
        expected_plan_id=getattr(args, "expected_plan", None),
        approval_id=getattr(args, "approval_id", None),
    )


def _project_menu_text(data: Mapping[str, object]) -> str:
    projects = data.get("projects")
    if not isinstance(projects, list) or not projects:
        return "Kayıtlı proje bulunamadı."
    rows = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        work_counts = project.get("work_counts")
        total = work_counts.get("total", 0) if isinstance(work_counts, dict) else 0
        rows.append([
            project.get("position", "-"),
            project.get("project_id", "-"),
            _display_status(project.get("status")),
            _display_status(project.get("integration_status")),
            _work_count_pair(project, "requests"),
            _work_count_pair(project, "defects"),
            _work_count_pair(project, "tasks"),
            total,
            _display_timestamp(project.get("last_updated_at")),
        ])
    table = _text_table(
        [
            "No",
            "Proje",
            "Durum",
            "Entegrasyon",
            "Talep A/G",
            "Defect A/G",
            "Görev A/G",
            "Toplam",
            "Son düzenleme UTC",
        ],
        rows,
    )
    return (
        f"{table}\n\n"
        "A: Aktif, G: Geçmiş\n"
        "Bir projeye girmek için sıra numarasını yazın. Örnek: 2"
    )


def _project_resume_text(data: Mapping[str, object]) -> str:
    if not data.get("matched"):
        lines = ["Proje bulunamadı."]
        suggestions = data.get("suggested_projects")
        if isinstance(suggestions, list) and suggestions:
            suggestion_rows = [
                [
                    item.get("position", "-"),
                    item.get("project_id", "-"),
                    f"{float(item.get('similarity', 0)):.0%}",
                ]
                for item in suggestions
                if isinstance(item, dict)
            ]
            lines.extend([
                "",
                "Benzer projeler:",
                _text_table(
                    ["No", "Proje", "Benzerlik"], suggestion_rows,
                ),
            ])
        navigation = data.get("navigation")
        if isinstance(navigation, dict):
            lines.extend(["", "Kayıtlı projeler:", _project_menu_text(navigation)])
        return "\n".join(lines)

    project = data.get("project")
    resume = data.get("resume")
    if not isinstance(project, dict) or not isinstance(resume, dict):
        return "Proje özeti kullanılamıyor."
    work = resume.get("work")
    if not isinstance(work, dict):
        work = {}
    summary = {
        "work_counts": work.get("work_counts", {}),
    }
    lines = [
        f"Proje: {project.get('project_id', '-')}",
        (
            "Talepler A/G: " + _work_count_pair(summary, "requests")
            + " | Defectler A/G: " + _work_count_pair(summary, "defects")
            + " | Görevler A/G: " + _work_count_pair(summary, "tasks")
        ),
    ]
    active_progress = work.get("active_progress")
    if isinstance(active_progress, list) and active_progress:
        progress_rows = []
        for progress in active_progress:
            if not isinstance(progress, dict):
                continue
            current = progress.get("current_step")
            current_title = current.get("title") if isinstance(current, dict) else "-"
            next_steps = progress.get("next_steps")
            next_title = "-"
            if isinstance(next_steps, list) and next_steps and isinstance(next_steps[0], dict):
                next_title = next_steps[0].get("title", "-")
            elif progress.get("verification_required") is True:
                next_title = "Görevi doğrula"
            completed = int(progress.get("completed_step_count", 0))
            total = int(progress.get("total_step_count", 0))
            progress_rows.append([
                _shorten(progress.get("work_item_id", "-"), 30),
                _display_status(progress.get("status")),
                f"{completed}/{total}",
                _shorten(current_title, 34),
                _shorten(next_title, 34),
            ])
        if progress_rows:
            lines.extend([
                "",
                "Aktif ilerleme:",
                _text_table(
                    ["İş", "Durum", "İlerleme", "Mevcut adım", "Sonraki adım"],
                    progress_rows,
                ),
            ])
    items = work.get("items")
    if isinstance(items, list) and items:
        rows = []
        project_id = str(project.get("project_id", ""))
        for item in items:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("work_item_id", "-"))
            project_prefix = project_id + "-"
            if identifier.startswith(project_prefix):
                identifier = identifier[len(project_prefix):]
            rows.append([
                _display_status(item.get("work_type")),
                _display_status(item.get("status")),
                _shorten(identifier, 32),
                _shorten(item.get("title", "-"), 36),
                _display_timestamp(item.get("last_updated_at")),
            ])
        lines.extend([
            "",
            "Son işler:",
            _text_table(
                ["Tür", "Durum", "Kimlik", "Başlık", "Son düzenleme UTC"],
                rows,
            ),
        ])
    else:
        lines.extend(["", "Bu projede kayıtlı iş bulunmuyor."])
    return "\n".join(lines)


def _work_list_text(data: Mapping[str, object]) -> str:
    if not data.get("matched"):
        lines = ["Proje bulunamadı."]
        navigation = data.get("navigation")
        if isinstance(navigation, dict):
            lines.extend(["", "Kayıtlı projeler:", _project_menu_text(navigation)])
        return "\n".join(lines)
    work = data.get("work")
    if not isinstance(work, dict):
        return "İş listesi kullanılamıyor."
    project_id = str(work.get("project_id", "-"))
    items = work.get("items")
    if not isinstance(items, list) or not items:
        return f"Proje: {project_id}\nFiltreye uyan kayıt bulunamadı."
    rows = []
    project_prefix = project_id + "-"
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("work_item_id", "-"))
        if identifier.startswith(project_prefix):
            identifier = identifier[len(project_prefix):]
        rows.append([
            _display_status(item.get("work_type")),
            _display_status(item.get("status")),
            _shorten(identifier, 38),
            _shorten(item.get("title", "-"), 44),
            item.get("revision", "-"),
            item.get("evidence_count", 0),
            _display_timestamp(item.get("last_updated_at")),
        ])
    lines = [
        f"Proje: {project_id}",
        _text_table(
            [
                "Tür",
                "Durum",
                "Kimlik",
                "Başlık",
                "Rev",
                "Kanıt",
                "Son düzenleme UTC",
            ],
            rows,
        ),
        (
            f"Gösterilen: {work.get('returned_count', len(rows))} / "
            f"{work.get('matched_count', len(rows))}"
        ),
    ]
    if work.get("truncated"):
        lines.append("Liste sınırlandı. Daha fazlası için --limit değerini artırın.")
    return "\n".join(lines)


def _work_document_migration_text(
    status: str,
    data: Mapping[str, object],
) -> str:
    plan = data.get("plan")
    if not isinstance(plan, dict):
        return "Belge yerleşim migration özeti kullanılamıyor."
    lines = [
        f"Proje: {plan.get('project_id', '-')}",
        f"Durum: {_display_status(status)}",
        (
            f"Belgeler: {plan.get('document_count', 0)} | "
            f"Kopyalanacak: {plan.get('copy_count', 0)} | "
            f"Hedef yerleşim: V{plan.get('target_layout_version', 2)}"
        ),
        (
            f"Kaynak eşleme: {plan.get('source_mapping_count', 0)} | "
            f"Fiziksel hedef: {plan.get('physical_target_count', 0)}"
        ),
        (
            f"Ad çakışma grubu: {plan.get('collision_group_count', 0)} | "
            f"İçerik çatışması: {plan.get('content_conflict_count', 0)} | "
            f"Tekilleştirilen grup: {plan.get('deduplicated_group_count', 0)}"
        ),
        (
            f"Çözümlenmemiş: {plan.get('unresolved_review_count', 0)} | "
            f"Hariç: {plan.get('excluded_count', 0)}"
        ),
    ]
    if plan.get("review_required") is True:
        values = plan.get("identity_review_required")
        rendered = (
            ", ".join(str(value) for value in values)
            if isinstance(values, list)
            else "-"
        )
        lines.append(f"Kimlik incelemesi gerekiyor: {rendered}")
    if status == "planned" and plan.get("no_op") is not True:
        lines.append("Uygulama için exact plan kimliği ve kullanıcı onayı gerekir.")
    if plan.get("cleanup_required") is True:
        lines.append(
            "Eski yerleşim korunur; temizlik ayrı bir exact plan ve onay gerektirir."
        )
    actions = data.get("next_actions")
    if isinstance(actions, list) and actions:
        lines.extend(["", "Sonraki adımlar:"])
        lines.extend(
            f"{index}. {value}"
            for index, value in enumerate(actions, start=1)
        )
    return "\n".join(lines)


def _work_document_processing_text(
    status: str,
    data: Mapping[str, object],
) -> str:
    plan = data.get("plan", {})
    if not isinstance(plan, Mapping):
        plan = {}
    lines = [f"İş belgesi işlemi: {status}"]
    project_id = plan.get("project_id")
    if project_id is not None:
        lines.append(f"Proje: {project_id}")
    manifest = plan.get("manifest_update", {})
    if plan.get("manifest_update_required") and isinstance(manifest, Mapping):
        lines.extend([
            "Önce belge manifesti güncellenecek.",
            f"Yeni belge: {manifest.get('new_document_count', 0)}",
            f"İçerik revizyonu: {manifest.get('revised_document_count', 0)}",
            f"Exact plan: {plan.get('plan_id', '-')}",
            "Work Graph ve indeks güncellemesi bu onaya dahil değildir.",
        ])
    else:
        lines.extend([
            f"Değişecek Work Item: {plan.get('changed_work_item_count', 0)}",
            f"Belge: {plan.get('document_count', 0)}",
            f"Exact plan: {plan.get('plan_id', '-')}",
        ])
    next_actions = data.get("next_actions", [])
    if isinstance(next_actions, list) and next_actions:
        lines.append("Sonraki adımlar:")
        lines.extend(f"- {value}" for value in next_actions)
    return "\n".join(lines)


def _work_index_text(
    status: str,
    data: Mapping[str, object],
) -> str:
    plan = data.get("plan")
    if not isinstance(plan, Mapping):
        return "Okunur iş indeksi özeti kullanılamıyor."
    lines = [
        f"Proje: {plan.get('project_id', '-')}",
        f"Durum: {_display_status(status)}",
        (
            f"Aktif: {plan.get('active_item_count', 0)} | "
            f"Geçmiş: {plan.get('historical_item_count', 0)} | "
            f"Listelenen: {plan.get('listed_item_count', 0)}"
        ),
        f"Atlanan geçmiş kayıt: {plan.get('omitted_item_count', 0)}",
        "Konum: proje KRCN home içindeki derived/work/WORK-INDEX.md",
    ]
    if status == "planned":
        lines.extend((
            f"Exact plan: {plan.get('plan_id', '-')}",
            "Uygulama türetilmiş görünümü yeniler; Work Graph JSON kayıtları otoriter kalır.",
        ))
    return "\n".join(lines)


def _research_action_text(
    status: str,
    data: Mapping[str, object],
) -> str:
    route = data.get("route")
    if not isinstance(route, dict):
        return "Araştırma isteği işlendi."
    if status == "choice-required":
        selection_reason = data.get("selection_reason")
        if route.get("needs_project") or selection_reason in {
            "multiple-projects-mentioned",
            "project-not-found",
        }:
            return (
                "Araştırma isteğini aldım. Önce ilgili projeyi seçmem veya "
                "proje dizininde çalışmam gerekiyor. İstek korunuyor."
            )
        return (
            "Araştırma isteğini aldım, ancak 'bunu' ifadesinin hangi konuyu "
            "gösterdiği belli değil. Konuyu bir cümleyle belirtin."
        )
    mode_names = {
        "quick": "hızlı",
        "standard": "standart",
        "deep": "detaylı",
        "comparison": "karşılaştırmalı",
        "root-cause": "kök neden",
    }
    outcome_names = {
        "research-only": "araştırma",
        "research-and-plan": "araştırma ve plan",
        "research-and-implement": "araştırma, plan ve onaylı uygulama",
    }
    mode = mode_names.get(str(route.get("mode")), str(route.get("mode", "-")))
    outcome = outcome_names.get(
        str(route.get("outcome")), str(route.get("outcome", "-"))
    )
    plan = data.get("plan")
    plan_id = plan.get("plan_id") if isinstance(plan, dict) else None
    lines = [
        f"Araştırma rotası: {mode} {outcome}",
        "Konu ve proje bağlamı çözüldü. Sağlayıcı veya değişiklik yetkisi verilmedi.",
    ]
    if status == "planned" and isinstance(plan_id, str):
        lines.append(f"Exact plan: {plan_id}")
        if data.get("next_stage") == "project-work-item-and-dispatch-planning":
            lines.append(
                "Bu plan araştırma alanını hazırlar. Sonrasında Work Item seçimi "
                "ve ayrı dispatch planı/onayı gerekir."
            )
        else:
            lines.append(
                "Bu plan araştırma alanını hazırlar. Sonrasında istemci veya "
                "operatör aracılı araştırma yürütülür."
            )
    elif status == "applied":
        if data.get("next_stage") == "project-work-item-and-dispatch-planning":
            lines.append(
                "Araştırma alanı hazırlandı. Sıradaki adım Work Item seçimi ve "
                "ayrı dispatch planıdır."
            )
        else:
            lines.append(
                "Araştırma alanı hazırlandı. İstemci veya operatör aracılı "
                "araştırma ile devam edilir."
            )
    return "\n".join(lines)


def _phase22_text(response: ServiceResponse) -> str:
    data = response.data
    operation = response.operation
    if operation in {"routing.decide", "routing.explain", "routing.record"}:
        decision = data.get("decision", {})
        selected = decision.get("selected", {}) if isinstance(decision, Mapping) else {}
        reasons = decision.get("reason_codes", []) if isinstance(decision, Mapping) else []
        comparison = data.get("comparison", {})
        comparison_status = (
            comparison.get("comparison_status", "-")
            if isinstance(comparison, Mapping)
            else "-"
        )
        persistence = (
            "kaydedildi" if data.get("persisted") else
            "exact plan gerekli" if operation == "routing.record" else
            "salt okunur"
        )
        return _text_table(
            ["Gölge rota", "Eşzamanlılık", "Nedenler", "Karşılaştırma", "Kayıt", "Yetki"],
            [[
                selected.get("route_mode", "-"),
                selected.get("maximum_concurrency", 1),
                ", ".join(reasons) if isinstance(reasons, list) else "-",
                comparison_status,
                persistence,
                "verilmedi",
            ]],
        )
    if operation == "autonomy.status":
        status = data.get("status", {})
        usage = status.get("usage", {}) if isinstance(status, Mapping) else {}
        return _text_table(["Ölçüm", "Değer"], [
            ["Durum", status.get("state", "-")],
            ["Duruş nedeni", status.get("stop_reason", "-")],
            ["Tur", usage.get("rounds", 0)],
            ["Maliyet", usage.get("cost_microunits", 0)],
            ["Devam", "evet" if status.get("resume_allowed") else "hayır"],
        ])
    if operation == "autonomy.morning":
        digest = data.get("digest", {})
        return _text_table(
            ["Run", "Durum", "Neden", "Tur", "Sonraki adım"],
            [[digest.get("run_id", "-"), digest.get("state", "-"),
              digest.get("stop_reason", "-"), digest.get("rounds", 0),
              digest.get("next_safe_action", "-")]],
        )
    if operation == "autonomy.admission":
        admission = data.get("admission", {})
        reasons = admission.get("reason_codes", [])
        return _text_table(
            ["Karar", "İstenen", "Kabul", "Tavan", "Nedenler"],
            [[admission.get("decision", "-"), admission.get("requested_claims", 0),
              admission.get("admitted_claims", 0), admission.get("concurrency_ceiling", 0),
              ", ".join(reasons) if isinstance(reasons, list) else "-"]],
        )
    if operation == "model.benchmark-prepare":
        if response.status == "blocked":
            return _text_table(
                ["Durum", "Neden", "Model", "Kalıcı host"],
                [["engelli", data.get("reason_code", "-"),
                  data.get("model_ref", "-"), "hayır"]],
            )
        plan = data.get("plan", {})
        return _text_table(
            ["Plan", "Model", "İş yükü", "Tekrar", "Host claim"],
            [[_shorten(data.get("expected_plan_id", "-"), 20), plan.get("model_ref", "-"),
              plan.get("workload_id", "-"), plan.get("repetitions", 0), "hayır"]],
        )
    if operation == "model.benchmark-execute":
        if response.status == "blocked":
            return _text_table(
                ["Durum", "Neden", "Model", "Çalıştırıldı"],
                [["engelli", data.get("reason_code", "-"), data.get("model_ref", "-"), "hayır"]],
            )
        result = data.get("result", {})
        aggregate = result.get("aggregate", {}) if isinstance(result, Mapping) else {}
        return _text_table(
            ["Durum", "Deneme", "Başarılı", "Kalıcı yazım"],
            [[response.status, aggregate.get("sample_count", 0),
              "evet" if aggregate.get("passed") else "hayır", "hayır"]],
        )
    if operation == "skill.evaluate":
        evaluation = data.get("evaluation", {})
        return _text_table(
            ["Aday", "Sonuç", "Deneme", "Başarılı", "Puan"],
            [[evaluation.get("candidate_id", "-"), evaluation.get("outcome", "-"),
              evaluation.get("trial_count", 0), evaluation.get("passed_trials", 0),
              evaluation.get("score_basis_points", 0)]],
        )
    if operation == "skill.plan-change":
        plan = data.get("plan", {})
        transition = f"{plan.get('from_state', '-')} -> {plan.get('to_state', '-')}"
        return _text_table(
            ["Skill", "Geçiş", "Plan", "Onay", "Uygulandı"],
            [[plan.get("skill_id", "-"), transition,
              _shorten(data.get("expected_plan_id", "-"), 20), "gerekli", "hayır"]],
        )
    if operation == "memory.context-effectiveness":
        evaluation = data.get("evaluation", {})
        metrics = evaluation.get("metrics", {}) if isinstance(evaluation, Mapping) else {}
        rows = [[key, value] for key, value in sorted(metrics.items())]
        rows.append(["passed", "evet" if evaluation.get("passed") else "hayır"])
        return _text_table(["Metrik", "Değer"], rows)
    report = data.get("report", {})
    return _text_table(["Hygiene", "Adet"], [
        ["Stale", len(report.get("stale_memory_ids", []))],
        ["Çakışma", len(report.get("conflict_memory_ids", []))],
        ["Duplicate grup", len(report.get("duplicate_groups", []))],
        ["Kullanılmayan", len(report.get("unused_memory_ids", []))],
        ["Retention", len(report.get("retention_candidate_ids", []))],
        ["Öneri", len(report.get("action_suggestions", []))],
    ])


def _print_service_response(
    response: ServiceResponse,
    output_format: str | None,
) -> int:
    rendered, exit_code = render_service_response(
        response,
        output_format,
        {
            "project_menu": _project_menu_text,
            "project_resume": _project_resume_text,
            "work_list": _work_list_text,
            "work_document_migration": _work_document_migration_text,
            "work_document_processing": _work_document_processing_text,
            "work_index": _work_index_text,
            "research_action": _research_action_text,
        },
    )
    print(rendered)
    return exit_code


def _configure_cli_stream_encoding() -> None:
    """Keep CLI output UTF-8 on Windows and other legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (OSError, ValueError):
            # Redirected or already-closed streams may not be reconfigurable.
            continue


def _active_project_data_root(explicit_data_root: Path | None) -> Path:
    if explicit_data_root is not None or os.environ.get("KRCN_HOME"):
        return resolve_user_home(explicit_data_root).path
    discovered = discover_initialized_project_home(Path.cwd())
    if discovered is not None:
        return discovered.path
    return resolve_user_home(None).path


def _project_learning_home(
    args: argparse.Namespace,
    repo_root: Path,
    source_root: Path,
) -> tuple[Path | None, ServiceResponse | None]:
    if args.data_root is not None or os.environ.get("KRCN_HOME"):
        if args.home_choice is not None or args.home_parent is not None:
            raise ApplicationServiceError(
                "project-home choice cannot be combined with data-root or KRCN_HOME"
            )
        return resolve_user_home(args.data_root).path, None

    marker = source_root / PROJECT_HOME_DIRECTORY / PROJECT_HOME_MANIFEST
    if marker.is_file() and not marker.is_symlink():
        if args.home_parent is not None or args.home_choice not in {None, "use-default"}:
            raise ApplicationServiceError(
                "initialized project home only accepts the use-default choice"
            )
        check = create_application_service(repo_root).execute(
            ServiceRequest(
                client_kind="cli",
                operation="project.home.initialize",
                arguments={
                    "project_root": str(source_root),
                    "choice": "use-default",
                },
                apply=args.apply,
                expected_plan_id=args.expected_plan,
                approval_id=args.approval_id,
            )
        )
        effects = check.data["plan"]["effect_plans"]
        if args.home_choice is not None or effects:
            return None, check
        return marker.parent.resolve(), None

    if args.home_choice is None:
        if args.home_parent is not None:
            raise ApplicationServiceError(
                "home-parent requires the choose-parent choice"
            )
        if args.apply or args.expected_plan or args.approval_id:
            raise ApplicationServiceError(
                "select a project-home choice before requesting apply"
            )
        operation = "project.home.resolve"
        arguments: dict[str, object] = {"project_root": str(source_root)}
        apply = False
    else:
        operation = "project.home.initialize"
        arguments = {
            "project_root": str(source_root),
            "choice": args.home_choice,
        }
        if args.home_parent is not None:
            arguments["selected_parent"] = str(args.home_parent.resolve())
        apply = args.apply

    request = ServiceRequest(
        client_kind="cli",
        operation=operation,
        arguments=arguments,
        apply=apply,
        expected_plan_id=args.expected_plan,
        approval_id=args.approval_id,
    )
    response = create_application_service(repo_root).execute(request)
    return None, response


def _run_project_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        if args.project_command == "learn":
            data_root, bootstrap = _project_learning_home(
                args,
                repo_root,
                args.source.resolve(),
            )
            if bootstrap is not None:
                return _print_service_response(bootstrap, args.format)
        else:
            data_root = _active_project_data_root(args.data_root)
        response = create_application_service(repo_root, data_root).execute(
            _project_service_request(args)
        )
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    return _print_service_response(response, args.format)


def _run_ask_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        try:
            navigation_intent = parse_project_navigation_intent(args.request)
        except ProjectNavigationError:
            navigation_intent = None
        if navigation_intent is not None:
            data_root = _active_project_data_root(args.data_root)
            response = create_application_service(repo_root, data_root).execute(
                ServiceRequest(
                    client_kind="cli",
                    operation=navigation_intent.operation,
                    arguments=navigation_intent.service_arguments(
                        str(Path.cwd().resolve())
                    ),
                )
            )
            response = ServiceResponse(
                request_id=response.request_id,
                operation=response.operation,
                status=response.status,
                data={
                    "route": navigation_intent.public_summary(),
                    **response.data,
                },
            )
            return _print_service_response(response, args.format)
        try:
            research_intent = parse_research_intent(repo_root, args.request)
        except ResearchIntentError as exc:
            raise ApplicationServiceError(str(exc)) from exc
        if research_intent is not None:
            data_root = _active_project_data_root(args.data_root)
            response = create_application_service(repo_root, data_root).execute(
                ServiceRequest(
                    client_kind="cli",
                    operation="research.action",
                    arguments={
                        "request_text": args.request,
                        "working_directory": str(
                            (args.source if args.source is not None else Path.cwd()).resolve()
                        ),
                        **(
                            {"context_text": args.context}
                            if args.context is not None
                            else {}
                        ),
                    },
                    apply=args.apply,
                    expected_plan_id=args.expected_plan,
                    approval_id=args.approval_id,
                )
            )
            return _print_service_response(response, args.format)
        if args.format is None:
            args.format = "json"
        try:
            document_intent = parse_work_document_intent(args.request)
        except WorkIntentError:
            document_intent = None
        if document_intent is not None:
            data_root = _active_project_data_root(args.data_root)
            response = create_application_service(repo_root, data_root).execute(
                ServiceRequest(
                    client_kind="cli",
                    operation="work.documents.process",
                    arguments=document_intent.service_arguments(),
                    apply=args.apply,
                    expected_plan_id=args.expected_plan,
                    approval_id=args.approval_id,
                )
            )
            response = ServiceResponse(
                request_id=response.request_id,
                operation=response.operation,
                status=response.status,
                data={"route": document_intent.public_summary(), **response.data},
            )
            return _print_service_response(response, args.format)
        try:
            work_intent = parse_work_create_intent(args.request)
        except WorkIntentError:
            work_intent = None
        if work_intent is not None:
            data_root = _active_project_data_root(args.data_root)
            response = create_application_service(repo_root, data_root).execute(
                ServiceRequest(
                    client_kind="cli",
                    operation="work.item.put",
                    arguments=work_intent.service_arguments(),
                    apply=args.apply,
                    expected_plan_id=args.expected_plan,
                    approval_id=args.approval_id,
                )
            )
            response = ServiceResponse(
                request_id=response.request_id,
                operation=response.operation,
                status=response.status,
                data={
                    "route": work_intent.public_summary(),
                    **response.data,
                },
            )
            return _print_service_response(response, args.format)
        route = route_project_request(repo_root, args.request)
        source_root = parse_project_learning_intent(
            args.request,
            source_root=args.source.resolve() if args.source is not None else None,
            intent_terms=route.terms,
        ).source_root
        data_root, bootstrap = _project_learning_home(
            args,
            repo_root,
            source_root,
        )
        if bootstrap is not None:
            return _print_service_response(bootstrap, args.format)
        if route.application_operation == "project.integrate":
            arguments = {
                "source_root": str(source_root),
                "scan_mode": "manual",
            }
        else:
            arguments = {"request_text": args.request}
            if args.source is not None:
                arguments["source_root"] = str(args.source.resolve())
        request = ServiceRequest(
            client_kind="cli",
            operation=route.application_operation,
            arguments=arguments,
            apply=args.apply,
            expected_plan_id=args.expected_plan,
            approval_id=args.approval_id,
        )
        response = create_application_service(repo_root, data_root).execute(request)
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    return _print_service_response(response, args.format)


def _run_integration_command(args: argparse.Namespace) -> int:
    try:
        if args.integration_command != "select":
            raise ApplicationServiceError("integration command is required")
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        data_root = _active_project_data_root(args.data_root)
        response = create_application_service(repo_root, data_root).execute(
            ServiceRequest(
                client_kind="cli",
                operation="integration.select-read-only",
                arguments={
                    "integration_id": args.integration_id,
                    "binding_id": args.binding_id,
                    "statement": args.statement,
                    "maximum_rows": args.maximum_rows,
                },
            )
        )
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    return _print_service_response(response, args.format)


def _core_service_request(args: argparse.Namespace) -> ServiceRequest:
    installation_root = str(args.installation.resolve())
    if args.command == "installation":
        if args.installation_command not in {"inspect", "verify"}:
            raise ApplicationServiceError("installation command is required")
        operation = f"installation.{args.installation_command}"
        arguments = {"installation_root": installation_root}
    elif args.command == "release":
        if args.release_command not in {"diff", "merge"}:
            raise ApplicationServiceError("release command is required")
        operation = f"release.{args.release_command}"
        arguments = {
            "installation_root": installation_root,
            "release_root": str(args.release_path.resolve()),
            "trusted_manifest_sha256": args.trusted_manifest_sha256,
        }
    elif args.command == "deployment" and args.deployment_command == "rollback":
        operation = "deployment.rollback"
        arguments = {
            "installation_root": installation_root,
            "deployment_id": args.deployment_id,
        }
    else:
        raise ApplicationServiceError("core service command is required")
    return ServiceRequest(
        client_kind="cli",
        operation=operation,
        arguments=arguments,
        apply=getattr(args, "apply", False),
        expected_plan_id=getattr(args, "expected_plan", None),
        approval_id=getattr(args, "approval_id", None),
    )


def _run_core_service_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        installation_root = args.installation.resolve()
        response = create_application_service(
            repo_root,
            installation_root / ".krcn",
        ).execute(
            _core_service_request(args)
        )
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    payload = response.as_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 3 if response.status in {"blocked", "unavailable"} else 0


def _load_phase_four_arguments(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ApplicationServiceError("request file must contain a JSON object")
    return payload


def _identity_decisions(values: list[str]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ApplicationServiceError(
                "identity decision must use KEY=request, KEY=defect, or KEY=exclude"
            )
        key, decision = (value.strip() for value in raw.split("=", 1))
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key)
            or decision not in {"request", "defect", "exclude"}
        ):
            raise ApplicationServiceError(
                "identity decision must use a portable key and request, defect, or exclude"
            )
        if key in decisions:
            raise ApplicationServiceError("identity decision key is duplicated")
        decisions[key] = decision
    return decisions


def _phase_four_service_request(args: argparse.Namespace) -> ServiceRequest:
    if args.command == "knowledge":
        if args.knowledge_command == "catalog":
            operation = "knowledge.catalog"
            arguments: dict[str, object] = {}
        elif args.knowledge_command in {"exact", "dependencies", "semantic"}:
            operation = f"knowledge.search-{args.knowledge_command}"
            arguments = _load_phase_four_arguments(args.request_file)
        elif args.knowledge_command == "index":
            operation = "knowledge.index-hybrid"
            arguments = {}
        elif args.knowledge_command == "hybrid":
            operation = "knowledge.search-hybrid"
            arguments = _load_phase_four_arguments(args.request_file)
        else:
            raise ApplicationServiceError("knowledge command is required")
    elif (
        args.command == "context-package"
        and args.context_package_command == "build"
    ):
        operation = "context.build"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "memory" and args.memory_command in {
        "propose",
        "review",
        "persist",
        "lifecycle",
        "hygiene",
        "context-effectiveness",
    }:
        operation = f"memory.{args.memory_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "autonomy" and args.autonomy_command in {
        "status",
        "morning",
        "admission",
    }:
        operation = f"autonomy.{args.autonomy_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "routing" and args.routing_command in {
        "decide",
        "explain",
        "record",
    }:
        operation = f"routing.{args.routing_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "outbound" and args.outbound_command == "assess":
        operation = "outbound.assess"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "sandbox" and args.sandbox_command == "plan":
        operation = "sandbox.plan"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "result" and args.result_command in {
        "normalize-native", "fan-in", "trace",
    }:
        operation = f"result.{args.result_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "skills" and args.skills_command in {
        "evaluate",
        "plan-change",
    }:
        operation = f"skill.{args.skills_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif (
        args.command == "models"
        and args.models_command == "benchmark"
        and args.benchmark_command in {"prepare", "execute"}
    ):
        operation = f"model.benchmark-{args.benchmark_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "work" and args.work_command in {
        "list",
        "put",
        "import",
        "copy-documents-initial",
        "migrate-document-layout",
        "process-documents",
        "index-readable",
        "index-semantic",
        "search",
        "query",
        "history",
    }:
        if args.work_command == "list":
            operation = "work.list"
            arguments = {
                "working_directory": str(Path.cwd().resolve()),
                "work_type": args.work_type,
                "lifecycle": args.lifecycle,
                "limit": args.limit,
            }
            if args.project is not None:
                arguments["project_ref"] = args.project
        elif args.work_command == "put":
            operation = "work.item.put"
            arguments = _load_phase_four_arguments(args.request_file)
        elif args.work_command == "import":
            operation = "work.import"
            arguments = {
                "source_root": str(args.source_root.resolve()),
                "import_request": _load_phase_four_arguments(args.request_file),
            }
        elif args.work_command == "copy-documents-initial":
            operation = "work.documents.copy-initial"
            arguments = {
                "project_id": args.project_id,
                "db_scripts_root": str(args.db_scripts_root.resolve()),
                "legacy_root": str(args.legacy_root.resolve()),
            }
        elif args.work_command == "migrate-document-layout":
            operation = "work.documents.migrate-layout"
            arguments = {
                "project_id": args.project_id,
                "reviewed_identity_decisions": _identity_decisions(
                    args.identity_decision
                ),
            }
        elif args.work_command == "process-documents":
            operation = "work.documents.process"
            arguments = {"project_id": args.project_id}
        elif args.work_command == "index-readable":
            operation = "work.index-readable"
            arguments = {"project_id": args.project_id}
        else:
            operation = f"work.{args.work_command}"
            arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "research" and args.research_command in {
        "prepare",
        "import-response",
        "status",
        "availability",
        "dispatch",
        "cancel",
        "runtime-status",
        "resume",
    }:
        operation = f"research.{args.research_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "runtime" and args.runtime_command in {
        "enqueue", "migrate-v2", "claim", "heartbeat", "bind-effect-claim",
        "bind-effect-receipt", "complete", "fail", "recover", "reconcile",
        "status",
    }:
        operation = f"runtime.queue.{args.runtime_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "oracle" and args.oracle_command in {
        "inspect", "collect", "refresh", "status", "index", "search",
        "dependencies",
    }:
        operation = f"database.oracle.{args.oracle_command}"
        arguments = _load_phase_four_arguments(args.request_file)
    elif args.command == "retrieval" and args.retrieval_command == "unified":
        operation = "retrieval.unified"
        arguments = _load_phase_four_arguments(args.request_file)
    else:
        raise ApplicationServiceError("Phase 4 service command is required")
    return ServiceRequest(
        client_kind="cli",
        operation=operation,
        arguments=arguments,
        apply=getattr(args, "apply", False),
        expected_plan_id=getattr(args, "expected_plan", None),
        approval_id=getattr(args, "approval_id", None),
    )


def _run_phase_four_service_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        data_root = resolve_user_home(args.data_root).path
        response = create_application_service(repo_root, data_root).execute(
            _phase_four_service_request(args)
        )
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    payload = response.as_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif response.operation == "work.list":
        print(_work_list_text(response.data))
    elif response.operation == "work.index-readable":
        print(_work_index_text(response.status, response.data))
    elif response.operation in {
        "autonomy.status",
        "autonomy.morning",
        "autonomy.admission",
        "routing.decide",
        "routing.explain",
        "routing.record",
        "model.benchmark-prepare",
        "model.benchmark-execute",
        "skill.evaluate",
        "skill.plan-change",
        "memory.hygiene",
        "memory.context-effectiveness",
    }:
        print(_phase22_text(response))
    elif response.operation == "outbound.assess":
        decision = response.data.get("decision", {})
        print(_text_table(
            ["Karar", "Provider", "Kategoriler", "Nedenler", "Payload"],
            [[decision.get("verdict", "-"), decision.get("provider_id", "-"),
              ", ".join(decision.get("data_categories", [])),
              ", ".join(decision.get("reason_codes", [])), "saklanmadi"]],
        ))
    elif response.operation == "sandbox.plan":
        plan = response.data.get("plan", {})
        print(_text_table(
            ["Plan", "HEAD", "Path", "Network", "Calistirma"],
            [[_shorten(plan.get("sandbox_plan_id", "-"), 20),
              _shorten(plan.get("source_head", "-"), 16),
              len(plan.get("allowed_paths", [])),
              "kapali" if plan.get("network_default_deny") else "yetkili",
              "hazir" if plan.get("execution_allowed") else "engelli"]],
        ))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 3 if response.status in {"blocked", "unavailable"} else 0


def _run_orchestrator_command(args: argparse.Namespace) -> int:
    try:
        if args.orchestrator_command is None:
            raise ApplicationServiceError("orchestrator command is required")
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        data_root = resolve_user_home(args.data_root).path
        request = ServiceRequest(
            client_kind="cli",
            operation=f"orchestrator.{args.orchestrator_command}",
            arguments=_load_phase_four_arguments(args.request_file),
            apply=args.apply,
            expected_plan_id=args.expected_plan,
        )
        response = create_application_service(repo_root, data_root).execute(request)
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    if args.format == "json":
        print(json.dumps(response.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 0


def _run_portability_command(args: argparse.Namespace) -> int:
    try:
        if args.portability_command not in {
            "backup",
            "restore",
            "migrate-repo-local",
            "migrate-project-home",
            "restore-project-home",
            "merge-project-home",
            "migrate-project-capsules",
            "export-project-capsule",
            "import-project-capsule",
        }:
            raise ApplicationServiceError("portability command is required")
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        if args.portability_command == "merge-project-home":
            target_home = args.target_home.resolve()
            if args.data_root is not None and args.data_root.resolve() != target_home:
                raise ApplicationServiceError(
                    "--data-root must match --target-home for project-home merge"
                )
            data_root = target_home
        else:
            data_root = resolve_user_home(args.data_root).path
        operation = f"portability.{args.portability_command}"
        if args.portability_command == "backup":
            arguments = {"archive_path": str(args.output.resolve())}
        elif args.portability_command == "restore":
            arguments = {"archive_path": str(args.input.resolve())}
        elif args.portability_command == "migrate-repo-local":
            arguments = {"backup_path": str(args.backup_output.resolve())}
        elif args.portability_command == "migrate-project-home":
            arguments = {
                "source_home": str(args.source_home.resolve()),
                "project_root": str(args.project.resolve()),
                "backup_path": str(args.backup_output.resolve()),
                "choice": args.home_choice,
            }
            if args.home_parent is not None:
                arguments["selected_parent"] = str(args.home_parent.resolve())
        elif args.portability_command == "restore-project-home":
            arguments = {
                "archive_path": str(args.input.resolve()),
                "project_root": str(args.project.resolve()),
                "choice": args.home_choice,
            }
            if args.home_parent is not None:
                arguments["selected_parent"] = str(args.home_parent.resolve())
        elif args.portability_command == "migrate-project-capsules":
            arguments = {"backup_path": str(args.backup_output.resolve())}
        elif args.portability_command == "export-project-capsule":
            arguments = {
                "project_id": args.project_id,
                "archive_path": str(args.output.resolve()),
                "mode": args.mode,
            }
        elif args.portability_command == "import-project-capsule":
            arguments = {"archive_path": str(args.input.resolve())}
        else:
            arguments = {
                "source_home": str(args.source_home.resolve()),
                "target_home": str(args.target_home.resolve()),
                "backup_directory": str(args.backup_directory.resolve()),
            }
        request = ServiceRequest(
            client_kind="cli",
            operation=operation,
            arguments=arguments,
            apply=args.apply,
            expected_plan_id=args.expected_plan,
            approval_id=args.approval_id,
        )
        response = create_application_service(repo_root, data_root).execute(request)
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    if args.format == "json":
        print(json.dumps(response.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 0


def _run_client_command(args: argparse.Namespace) -> int:
    try:
        if args.client_command not in {"bootstrap", "capabilities", "delegation"}:
            raise ApplicationServiceError("client command is required")
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        data_root = resolve_user_home(args.data_root).path
        if args.client_command == "bootstrap":
            operation = "client.bootstrap"
            arguments = {}
            apply = args.apply
            expected_plan = args.expected_plan
            approval_id = args.approval_id
        elif args.client_command in {"capabilities", "delegation"}:
            max_parallel_agents = args.max_parallel_agents
            if max_parallel_agents is None:
                max_parallel_agents = 2 if args.parallel_subagents else 1
            arguments = {
                "session_id": args.session_id,
                "client_id": args.client_id,
                "capabilities": {
                    "native_subagents": args.native_subagents,
                    "parallel_subagents": args.parallel_subagents,
                    "per_agent_model_selection": args.per_agent_model_selection,
                    "agent_cancellation": args.agent_cancellation,
                    "structured_results": args.structured_results,
                    "isolated_role_execution": args.isolated_role_execution,
                },
                "max_parallel_agents": max_parallel_agents,
            }
            operation = "client.capabilities"
            if args.client_command == "delegation":
                operation = "client.delegation"
                arguments.update(
                    {
                        "work_class": args.work_class,
                        "project_matched": args.project_matched,
                    }
                )
            apply = False
            expected_plan = None
            approval_id = None
        else:
            raise ApplicationServiceError("client command is required")
        response = create_application_service(repo_root, data_root).execute(
            ServiceRequest(
                client_kind="cli",
                operation=operation,
                arguments=arguments,
                apply=apply,
                expected_plan_id=expected_plan,
                approval_id=approval_id,
            )
        )
    except (ApplicationServiceError, OSError, ValueError) as exc:
        _print_error(exc)
        return 2
    printed = _print_service_response(response, args.format)
    return 3 if response.status == "blocked" else printed


def _run_model_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        data_root = resolve_user_home(args.data_root).path
        service_options = {}
        if args.model_command == "resolve":
            bindings = {}
            for value in args.bind:
                candidate, separator, model_id = value.partition("=")
                if not separator or not candidate or not model_id or candidate in bindings:
                    raise ApplicationServiceError(
                        "each model binding must be unique CANDIDATE=MODEL"
                    )
                bindings[candidate] = model_id
            arguments = {
                "available_bindings": bindings,
                "authorized_refs": args.authorize,
            }
            if args.role is not None:
                arguments["role"] = args.role
            else:
                arguments["workload"] = args.workload
            operation = "model.resolve"
        elif args.model_command == "inventory":
            payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict) or set(payload) != {"models"}:
                raise ApplicationServiceError(
                    "model inventory input must contain only models"
                )
            arguments = payload
            operation = "model.inventory"
        elif args.model_command == "list":
            arguments = {}
            operation = "model.list"
        elif args.model_command == "health":
            if args.apply:
                secret_provider = OpenCodeSecretProvider(args.opencode_config.resolve())
                service_options["model_health_probes"] = {
                    "litellm": OpenAICompatibleModelHealthProbe(
                        secret_provider.resolve,
                        args.credential_reference,
                    )
                }
            arguments = {
                "model_ref": args.model_ref,
                "endpoint": args.endpoint,
                "retention_assumptions": args.retention_assumptions,
                "session_id": args.session_id,
                "force_retest": args.force_retest,
            }
            operation = "model.health"
        elif args.model_command == "health-list":
            arguments = {}
            operation = "model.health-list"
        elif args.model_command == "benchmark-suite":
            arguments = {"project_id": args.project_id}
            operation = "model.benchmark-suite"
        elif args.model_command == "benchmark-list":
            arguments = {}
            if args.project is not None:
                arguments["project_id"] = args.project
            operation = "model.benchmark-list"
        else:
            raise ApplicationServiceError("model command is required")
        response = create_application_service(
            repo_root,
            data_root,
            **service_options,
        ).execute(
            ServiceRequest(
                client_kind="cli",
                operation=operation,
                arguments=arguments,
                apply=getattr(args, "apply", False),
                expected_plan_id=getattr(args, "expected_plan", None),
                approval_id=getattr(args, "approval_id", None),
            )
        )
    except (ApplicationServiceError, OSError, ValueError, json.JSONDecodeError) as exc:
        _print_error(exc)
        return 2
    return _print_service_response(response, args.format)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_cli_stream_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "context":
        try:
            repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        except ValueError as exc:
            _print_error(exc)
            return 2
        context_args = ["--repo", str(repo_root), "--format", args.format]
        if args.validate_only:
            context_args.append("--validate-only")
        return context_main(context_args)

    if args.command in {"doctor", "validate"}:
        try:
            repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        except ValueError as exc:
            _print_error(exc)
            return 2
        checks = run_doctor(repo_root, args.data_root)
        if args.format == "json":
            print(json.dumps([item.as_dict() for item in checks], indent=2))
        else:
            for item in checks:
                status = "PASS" if item.passed else "FAIL"
                print(f"{status}\t{item.check_id}\t{item.detail}")
        return 0 if all(item.passed for item in checks) else 1

    if args.command == "project":
        if args.project_command is None:
            parser.parse_args(["project", "--help"])
        return _run_project_command(args)

    if args.command == "ask":
        return _run_ask_command(args)

    if args.command == "integration":
        return _run_integration_command(args)

    if args.command in {"installation", "release", "deployment"}:
        return _run_core_service_command(args)

    if args.command in {
        "knowledge",
        "context-package",
        "memory",
        "work",
        "research",
        "runtime",
        "oracle",
        "retrieval",
        "autonomy",
        "skills",
        "models",
        "routing",
        "result",
        "outbound",
        "sandbox",
    }:
        return _run_phase_four_service_command(args)

    if args.command == "orchestrator":
        return _run_orchestrator_command(args)

    if args.command == "portability":
        return _run_portability_command(args)

    if args.command == "client":
        return _run_client_command(args)

    if args.command == "model":
        return _run_model_command(args)

    if args.command != "catalog":
        parser.print_help()
        return 0

    commands = compatibility_registry().all(include_internal=args.include_internal)
    if args.format == "json":
        print(json.dumps([item.as_dict() for item in commands], ensure_ascii=False, indent=2))
    else:
        for item in commands:
            print(f"{item.command}\t{item.behavior}\t{item.disposition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

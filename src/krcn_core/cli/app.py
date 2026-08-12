"""Safe KRCN Core CLI baseline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from krcn_core.application import (
    ApplicationServiceError,
    ServiceRequest,
    ServiceResponse,
    create_application_service,
)
from krcn_core.doctor import run_doctor
from krcn_core.intent_routing import project_learning_route
from krcn_core.project_home import (
    PROJECT_HOME_DIRECTORY,
    PROJECT_HOME_MANIFEST,
    discover_initialized_project_home,
)
from krcn_core.project_learning_intent import parse_project_learning_intent
from krcn_core.repository_context import main as context_main
from krcn_core.user_home import resolve_user_home

from .registry import compatibility_registry


def discover_repo_root(start: Path | None = None) -> Path:
    """Find a repository context manifest without using machine-specific paths."""

    candidate = (start or Path.cwd()).resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / ".ai" / "repository-context.json").is_file():
            return directory
    raise ValueError("repository context manifest was not found")


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
        doctor.add_argument("--format", choices=("text", "json"), default="text")
    ask = subparsers.add_parser(
        "ask",
        help="Route a natural-language request through shared services",
    )
    ask.add_argument("request")
    ask.add_argument("--source", type=Path)
    _add_service_options(ask, mutation=True)
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
    project_inspect = project_commands.add_parser(
        "inspect",
        help="Inspect a registered project with redacted source bindings",
    )
    project_inspect.add_argument("project_id")
    _add_service_options(project_inspect)
    project_learn = project_commands.add_parser(
        "learn",
        help="Learn a local project from only its directory",
    )
    project_learn.add_argument("source", type=Path)
    _add_service_options(project_learn, mutation=True)
    _add_project_home_choice_options(project_learn)
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
    elif args.project_command == "learn":
        operation = "project.learn"
        arguments = {
            "request_text": str(args.source.resolve()),
            "source_root": str(args.source.resolve()),
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


def _print_service_response(response: ServiceResponse, output_format: str) -> int:
    payload = response.as_dict()
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 0


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
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _print_service_response(response, args.format)


def _run_ask_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        source_root = parse_project_learning_intent(
            args.request,
            source_root=args.source.resolve() if args.source is not None else None,
            intent_terms=project_learning_route(repo_root).terms,
        ).source_root
        data_root, bootstrap = _project_learning_home(
            args,
            repo_root,
            source_root,
        )
        if bootstrap is not None:
            return _print_service_response(bootstrap, args.format)
        arguments: dict[str, object] = {"request_text": args.request}
        if args.source is not None:
            arguments["source_root"] = str(args.source.resolve())
        request = ServiceRequest(
            client_kind="cli",
            operation="project.learn",
            arguments=arguments,
            apply=args.apply,
            expected_plan_id=args.expected_plan,
            approval_id=args.approval_id,
        )
        response = create_application_service(repo_root, data_root).execute(request)
    except (ApplicationServiceError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
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
        print(f"ERROR: {exc}", file=sys.stderr)
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
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    payload = response.as_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 0


def _load_phase_four_arguments(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ApplicationServiceError("request file must contain a JSON object")
    return payload


def _phase_four_service_request(args: argparse.Namespace) -> ServiceRequest:
    if args.command == "knowledge":
        if args.knowledge_command == "catalog":
            operation = "knowledge.catalog"
            arguments: dict[str, object] = {}
        elif args.knowledge_command in {"exact", "dependencies", "semantic"}:
            operation = f"knowledge.search-{args.knowledge_command}"
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
    }:
        operation = f"memory.{args.memory_command}"
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
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    payload = response.as_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 0


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
        print(f"ERROR: {exc}", file=sys.stderr)
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
        }:
            raise ApplicationServiceError("portability command is required")
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
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
        else:
            arguments = {
                "archive_path": str(args.input.resolve()),
                "project_root": str(args.project.resolve()),
                "choice": args.home_choice,
            }
            if args.home_parent is not None:
                arguments["selected_parent"] = str(args.home_parent.resolve())
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
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(response.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{response.status}\t{response.operation}")
        print(json.dumps(response.data, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "context":
        try:
            repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        context_args = ["--repo", str(repo_root), "--format", args.format]
        if args.validate_only:
            context_args.append("--validate-only")
        return context_main(context_args)

    if args.command in {"doctor", "validate"}:
        try:
            repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        checks = run_doctor(repo_root)
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

    if args.command in {"knowledge", "context-package", "memory"}:
        return _run_phase_four_service_command(args)

    if args.command == "orchestrator":
        return _run_orchestrator_command(args)

    if args.command == "portability":
        return _run_portability_command(args)

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

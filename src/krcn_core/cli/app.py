"""Safe KRCN Core CLI baseline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from krcn_core.application import (
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.doctor import run_doctor
from krcn_core.local_store import LocalWorkspaceStore
from krcn_core.mutation_gate import OwnershipResolver
from krcn_core.repository_context import main as context_main

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


def _project_service_request(args: argparse.Namespace) -> ServiceRequest:
    if args.project_command == "list":
        operation = "project.list"
        arguments: dict[str, object] = {}
    elif args.project_command == "inspect":
        operation = "project.inspect"
        arguments = {"project_id": args.project_id}
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


def _run_project_command(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve() if args.repo else discover_repo_root()
        data_root = args.data_root.resolve() if args.data_root else repo_root / ".krcn"
        store = LocalWorkspaceStore(
            data_root,
            OwnershipResolver.from_repository(repo_root),
        )
        response = KrcnApplicationService(repo_root, store).execute(
            _project_service_request(args)
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

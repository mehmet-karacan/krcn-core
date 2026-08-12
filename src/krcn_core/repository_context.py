"""Client-neutral repository context resolution for KRCN Core."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence


REQUIRED_CANONICAL_KEYS = {
    "instructions",
    "orientation",
    "current_work",
    "roadmap",
    "ownership",
    "source_binding_schema",
    "user_policy_schema",
    "mutation_plan_schema",
    "provider_request_schema",
    "local_record_schema",
    "onboarding_plan_schema",
    "discovery_result_schema",
    "adapter_schema",
    "adapter_operation_schema",
    "integration_schema",
    "source_state_schema",
    "rescan_plan_schema",
    "project_home_merge_plan_schema",
    "application_request_schema",
    "application_response_schema",
    "phase_baseline_schema",
    "phase_two_baseline",
    "phase_three_baseline",
    "phase_three_merge_boundary",
    "phase_four_boundary",
    "phase_four_baseline",
    "phase_five_boundary",
    "phase_five_baseline",
    "orchestration_boundary",
    "orchestration_boundary_schema",
    "task_intent_schema",
    "capability_registry",
    "capability_registry_schema",
    "task_plan_schema",
    "task_authorization_schema",
    "worker_execution_schema",
    "task_verification_schema",
    "orchestration_state_schema",
    "orchestration_event_schema",
    "orchestration_checkpoint_schema",
    "orchestration_handoff_schema",
    "release_manifest_schema",
    "installation_state_schema",
    "installation_inspection_schema",
    "release_trust",
    "release_diff_schema",
    "merge_plan_schema",
    "backup_manifest_schema",
    "deployment_journal_schema",
    "migration_execution",
    "policy_layers",
    "cli_inventory",
    "cli_baseline",
    "cli_installation",
    "provider_policy",
    "embedding_model_catalog",
    "embedding_model_catalog_schema",
    "remote_embedding_providers",
    "import_policy",
}

REQUIRED_CLIENTS = {
    "codex",
    "claude-code",
    "generic-ai",
    "plugin",
    "sdk",
    "mcp",
}

ALLOWED_ADAPTER_MODES = {"native", "import", "document", "manifest"}

REQUIRED_TASK_FIELDS = {
    "goal",
    "scope",
    "sources",
    "constraints",
    "acceptance_criteria",
    "ownership_impact",
    "verification_evidence",
}


class RepositoryContextError(ValueError):
    """Raised when repository context cannot be resolved safely."""


@dataclass(frozen=True)
class ResolvedRepositoryContext:
    """Validated repository context with relative, portable references."""

    manifest: dict
    current_work: dict

    def summary(self) -> dict:
        """Return a compact client-neutral context summary."""

        return {
            "schema_version": self.manifest["schema_version"],
            "project": self.manifest["project"],
            "current_work": self.current_work,
            "canonical": self.manifest["canonical"],
            "read_order": self.manifest["bootstrap"]["read_order"],
            "task_contract": self.manifest["bootstrap"]["task_contract"],
            "verification_commands": self.manifest["bootstrap"][
                "verification_commands"
            ],
            "client_adapters": self.manifest["client_adapters"],
            "data_policy": self.manifest["data_policy"],
        }


def load_json_object(path: Path) -> dict:
    """Load a UTF-8 JSON object with a useful validation error."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepositoryContextError(f"Missing context document: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RepositoryContextError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RepositoryContextError(f"Context document must be an object: {path.name}")
    return value


def resolve_repo_reference(repo_root: Path, value: str) -> Path:
    """Resolve a portable repository-relative reference without path escape."""

    if not isinstance(value, str) or not value.strip():
        raise RepositoryContextError("Repository reference must be a non-empty string")

    posix_path = PurePosixPath(value)
    if posix_path.is_absolute() or PureWindowsPath(value).is_absolute():
        raise RepositoryContextError("Absolute repository reference is prohibited")
    if "\\" in value:
        raise RepositoryContextError("Repository reference must use forward slashes")
    if ".." in posix_path.parts:
        raise RepositoryContextError("Repository reference cannot escape the root")

    root = repo_root.resolve()
    resolved = root.joinpath(*posix_path.parts).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RepositoryContextError("Repository reference cannot escape the root") from exc
    return resolved


def _validate_reference(
    repo_root: Path,
    value: object,
    label: str,
    errors: list[str],
) -> None:
    try:
        resolved = resolve_repo_reference(repo_root, value)
    except RepositoryContextError as exc:
        errors.append(f"{label}: {exc}")
        return
    if not resolved.is_file():
        errors.append(f"{label}: referenced file does not exist")


def validate_repository_context(repo_root: Path) -> list[str]:
    """Validate context routing, current work, and safe client entrypoints."""

    errors: list[str] = []
    manifest_path = repo_root / ".ai" / "repository-context.json"
    try:
        manifest = load_json_object(manifest_path)
    except RepositoryContextError as exc:
        return [str(exc)]

    if manifest.get("schema_version") != 1:
        errors.append("repository context schema_version must be 1")
    _validate_reference(repo_root, manifest.get("schema_ref"), "schema_ref", errors)

    project = manifest.get("project")
    required_project_keys = {"id", "name", "purpose", "architecture_owner"}
    if not isinstance(project, dict) or not required_project_keys.issubset(project):
        errors.append("project metadata is incomplete")

    canonical = manifest.get("canonical")
    if not isinstance(canonical, dict):
        return errors + ["canonical context references must be an object"]
    missing_canonical = REQUIRED_CANONICAL_KEYS - set(canonical)
    if missing_canonical:
        errors.append(
            "missing canonical references: " + ", ".join(sorted(missing_canonical))
        )
    for key, value in canonical.items():
        _validate_reference(repo_root, value, f"canonical.{key}", errors)

    bootstrap = manifest.get("bootstrap")
    if not isinstance(bootstrap, dict):
        errors.append("bootstrap must be an object")
    else:
        read_order = bootstrap.get("read_order")
        if not isinstance(read_order, list) or not read_order:
            errors.append("bootstrap.read_order must be a non-empty list")
        else:
            for index, value in enumerate(read_order):
                _validate_reference(
                    repo_root,
                    value,
                    f"bootstrap.read_order[{index}]",
                    errors,
                )
        task_contract = bootstrap.get("task_contract")
        if not isinstance(task_contract, list) or not REQUIRED_TASK_FIELDS.issubset(
            task_contract
        ):
            errors.append("bootstrap.task_contract is incomplete")
        commands = bootstrap.get("verification_commands")
        if not isinstance(commands, list) or not commands:
            errors.append("bootstrap.verification_commands must be a non-empty list")

    adapters = manifest.get("client_adapters")
    if not isinstance(adapters, dict):
        errors.append("client_adapters must be an object")
    else:
        missing_clients = REQUIRED_CLIENTS - set(adapters)
        if missing_clients:
            errors.append("missing client adapters: " + ", ".join(sorted(missing_clients)))
        for client_id, adapter in adapters.items():
            if not isinstance(adapter, dict):
                errors.append(f"client_adapters.{client_id} must be an object")
                continue
            _validate_reference(
                repo_root,
                adapter.get("entrypoint"),
                f"client_adapters.{client_id}.entrypoint",
                errors,
            )
            if adapter.get("mode") not in ALLOWED_ADAPTER_MODES:
                errors.append(f"client_adapters.{client_id}.mode is invalid")
            if "automatic" in adapter and not isinstance(adapter["automatic"], bool):
                errors.append(f"client_adapters.{client_id}.automatic must be boolean")

    expected_data_policy = {
        "offline_by_default": True,
        "local_data_in_git": False,
        "implicit_provider_discovery": False,
        "user_data_mutation_requires_approval": True,
    }
    if manifest.get("data_policy") != expected_data_policy:
        errors.append("repository context data policy is not safe by default")

    current_work_ref = canonical.get("current_work")
    try:
        current_work_path = resolve_repo_reference(repo_root, current_work_ref)
        current_work = load_json_object(current_work_path)
    except RepositoryContextError as exc:
        errors.append(f"current work: {exc}")
        return errors

    if current_work.get("schema_version") != 1:
        errors.append("current work schema_version must be 1")
    _validate_reference(
        repo_root,
        current_work.get("schema_ref"),
        "current_work.schema_ref",
        errors,
    )
    _validate_reference(repo_root, current_work.get("plan_ref"), "current_work.plan_ref", errors)
    progress_refs = current_work.get("progress_refs")
    if not isinstance(progress_refs, list):
        errors.append("current_work.progress_refs must be a list")
    else:
        for index, value in enumerate(progress_refs):
            _validate_reference(
                repo_root,
                value,
                f"current_work.progress_refs[{index}]",
                errors,
            )
    next_actions = current_work.get("next_actions")
    if not isinstance(next_actions, list) or not next_actions:
        errors.append("current_work.next_actions must be a non-empty list")
    expected_approval_gates = {
        "tracked_source_import": True,
        "user_data_mutation": True,
        "remote_provider_use": True,
    }
    if current_work.get("approval_gates") != expected_approval_gates:
        errors.append("current work approval gates must remain enabled")

    return errors


def resolve_repository_context(repo_root: Path) -> ResolvedRepositoryContext:
    """Load repository context after all references pass validation."""

    errors = validate_repository_context(repo_root)
    if errors:
        raise RepositoryContextError("; ".join(errors))
    manifest = load_json_object(repo_root / ".ai" / "repository-context.json")
    current_work_path = resolve_repo_reference(
        repo_root, manifest["canonical"]["current_work"]
    )
    current_work = load_json_object(current_work_path)
    return ResolvedRepositoryContext(manifest=manifest, current_work=current_work)


def _render_text(summary: dict) -> str:
    project = summary["project"]
    current = summary["current_work"]
    lines = [
        f"Project: {project['name']}",
        f"Purpose: {project['purpose']}",
        f"Workstream: {current['workstream_id']}",
        f"Status: {current['status']}",
        f"Plan: {current['plan_ref']}",
        "Read order:",
    ]
    lines.extend(f"- {path}" for path in summary["read_order"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve KRCN Core repository context")
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        resolved = resolve_repository_context(args.repo.resolve())
    except RepositoryContextError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.validate_only:
        print("Repository context validation passed.")
        return 0

    summary = resolved.summary()
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(_render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

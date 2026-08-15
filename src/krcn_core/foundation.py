"""Foundation validation for ownership, providers, and safe imports."""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .json_documents import (
    JsonDocumentError,
    parse_json_bytes,
    pretty_json_bytes,
)


REQUIRED_OWNERSHIP_CLASSES = {
    "core": "replace-managed",
    "runtime": "preserve",
    "user-data": "preserve",
    "derived": "migrate-or-rebuild",
    "secrets": "preserve",
    "unmanaged": "preserve",
}

REQUIRED_IMPORT_GATES = {
    "ownership-classified",
    "secret-scan-clean",
    "portability-scan-clean",
    "network-disabled",
    "synthetic-fixtures-only",
    "hermetic-tests-pass",
    "staged-diff-reviewed",
    "user-approved",
}

REQUIRED_INFORMATION_CLASSES = {
    "authoritative-source",
    "knowledge",
    "memory",
    "state",
    "history",
    "derived",
}

REQUIRED_ORCHESTRATION_ROLES = {"planner", "worker", "verifier"}
REQUIRED_ORCHESTRATION_STAGES = (
    "intake",
    "context",
    "plan",
    "approval",
    "execute",
    "verify",
    "record",
)
REQUIRED_TASK_CONTRACT_FIELDS = {
    "goal",
    "scope",
    "sources",
    "constraints",
    "acceptance_criteria",
    "ownership_impact",
    "verification_evidence",
}
REQUIRED_APPROVAL_TRIGGERS = {
    "scope-change",
    "user-data-mutation",
    "remote-provider-use",
    "irreversible-effect",
    "policy-change",
    "capability-escalation",
}


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    detail: str

    def render(self) -> str:
        return f"{self.code}: {self.path}: {self.detail}"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing configuration: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def validate_ownership_manifest(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("ownership schema_version must be 1")

    default = data.get("default_unmatched", {})
    if default != {
        "ownership": "unmanaged",
        "merge_strategy": "preserve",
        "approval_required": True,
    }:
        errors.append("unmatched paths must be preserved and require approval")

    classes = data.get("classes")
    if not isinstance(classes, list):
        return errors + ["ownership classes must be a list"]

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for item in classes:
        if not isinstance(item, dict):
            errors.append("each ownership class must be an object")
            continue
        class_id = item.get("id")
        strategy = item.get("merge_strategy")
        paths = item.get("paths")
        if class_id in seen_ids:
            errors.append(f"duplicate ownership class: {class_id}")
        seen_ids.add(class_id)
        if REQUIRED_OWNERSHIP_CLASSES.get(class_id) != strategy:
            errors.append(f"invalid merge strategy for ownership class: {class_id}")
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            errors.append(f"paths must be a string list for ownership class: {class_id}")
            continue
        for path in paths:
            if path in seen_paths:
                errors.append(f"duplicate ownership path: {path}")
            seen_paths.add(path)

    missing = set(REQUIRED_OWNERSHIP_CLASSES) - seen_ids
    if missing:
        errors.append(f"missing ownership classes: {', '.join(sorted(missing))}")
    return errors


def validate_provider_policy(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("provider schema_version must be 1")
    if data.get("default_mode") != "offline":
        errors.append("provider default_mode must be offline")
    if data.get("implicit_provider_discovery") is not False:
        errors.append("implicit provider discovery must be disabled")

    network = data.get("network", {})
    expected_network = {
        "default_action": "deny",
        "diagnostics_may_upload": False,
        "tests_may_connect": False,
        "imports_may_connect": False,
    }
    if network != expected_network:
        errors.append("network policy must deny diagnostics, tests, and imports")

    remote = data.get("remote_providers", {})
    if remote.get("enabled") is not False:
        errors.append("remote providers must be disabled by default")
    if remote.get("explicit_opt_in_required") is not True:
        errors.append("remote providers must require explicit opt-in")
    disclosures = set(remote.get("required_disclosures", []))
    required = {
        "provider",
        "endpoint",
        "data_categories",
        "operation_scope",
        "retention_assumptions",
    }
    if not required.issubset(disclosures):
        errors.append("remote provider disclosures are incomplete")
    return errors


def validate_import_policy(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("import schema_version must be 1")
    if data.get("network_required_mode") != "offline":
        errors.append("imports must require offline mode")
    if not isinstance(data.get("maximum_text_file_bytes"), int):
        errors.append("maximum_text_file_bytes must be an integer")
    if not isinstance(data.get("blocked_globs"), list):
        errors.append("blocked_globs must be a list")
    if not isinstance(data.get("content_detectors"), list):
        errors.append("content_detectors must be a list")
    gates = set(data.get("required_gates", []))
    if not REQUIRED_IMPORT_GATES.issubset(gates):
        errors.append("required import gates are incomplete")
    return errors


def validate_information_classes(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_ref") != "schemas/information-classes.schema.json":
        errors.append("information class schema reference is invalid")
    if data.get("schema_version") != 1:
        errors.append("information class schema_version must be 1")
    classes = data.get("classes")
    if not isinstance(classes, list):
        return errors + ["information classes must be a list"]
    by_id = {}
    for item in classes:
        if not isinstance(item, dict):
            errors.append("each information class must be an object")
            continue
        class_id = item.get("id")
        if not isinstance(class_id, str):
            errors.append("information class id must be a string")
            continue
        if class_id in by_id:
            errors.append(f"duplicate information class: {class_id}")
        by_id[class_id] = item
        ownerships = item.get("allowed_record_ownerships")
        if not isinstance(ownerships, list) or not ownerships:
            errors.append(f"information class ownership is invalid: {class_id}")
        elif "secrets" in ownerships:
            errors.append(f"secret ownership is prohibited: {class_id}")
    missing = REQUIRED_INFORMATION_CLASSES - set(by_id)
    extra = set(by_id) - REQUIRED_INFORMATION_CLASSES
    if missing:
        errors.append("missing information classes: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unexpected information classes: " + ", ".join(sorted(extra)))
    authoritative = by_id.get("authoritative-source", {})
    if authoritative.get("source_of_truth") is not True:
        errors.append("authoritative source must be the source of truth")
    for class_id, item in by_id.items():
        if class_id != "authoritative-source" and item.get("source_of_truth") is not False:
            errors.append(f"non-authoritative class claims source of truth: {class_id}")
    derived = by_id.get("derived", {})
    if derived.get("rebuildable") is not True or derived.get("durability") != "rebuildable":
        errors.append("derived information must be rebuildable")
    memory = by_id.get("memory", {})
    if memory.get("requires_approval_to_persist") is not True:
        errors.append("durable memory must require approval")
    return errors


def validate_orchestration_boundary(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_ref") != "schemas/orchestration-boundary.schema.json":
        errors.append("orchestration boundary schema reference is invalid")
    if data.get("schema_version") != 1:
        errors.append("orchestration boundary schema_version must be 1")
    if data.get("baseline_ref") != ".ai/phase-4-baseline.json":
        errors.append("orchestration must start from the Phase 4 baseline")

    roles = data.get("roles")
    if not isinstance(roles, list):
        return errors + ["orchestration roles must be a list"]
    by_id = {
        item.get("id"): item
        for item in roles
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if set(by_id) != REQUIRED_ORCHESTRATION_ROLES or len(roles) != 3:
        errors.append("orchestration roles must be planner, worker, and verifier")
    if by_id.get("planner", {}).get("may_mutate") is not False:
        errors.append("planner must not mutate")
    if by_id.get("worker", {}).get("may_mutate") is not True:
        errors.append("worker must be the only mutation-capable role")
    if by_id.get("verifier", {}).get("may_mutate") is not False:
        errors.append("verifier must not mutate")
    if any(item.get("may_approve") is not False for item in by_id.values()):
        errors.append("orchestration roles must not self-approve")

    if tuple(data.get("stages", ())) != REQUIRED_ORCHESTRATION_STAGES:
        errors.append("orchestration stages are incomplete or out of order")
    if set(data.get("task_contract_fields", ())) != REQUIRED_TASK_CONTRACT_FIELDS:
        errors.append("orchestration task contract fields are incomplete")
    if set(data.get("approval_triggers", ())) != REQUIRED_APPROVAL_TRIGGERS:
        errors.append("orchestration approval triggers are incomplete")

    invariants = data.get("invariants")
    expected_invariants = {
        "chat_history_is_authority": False,
        "plan_grants_execution": False,
        "worker_self_approves": False,
        "verification_required": True,
        "critical_change_requires_user_approval": True,
        "exact_plan_required_for_mutation": True,
        "resume_from_persistent_state": True,
        "client_rules_may_diverge": False,
    }
    if invariants != expected_invariants:
        errors.append("orchestration safety invariants are invalid")
    return errors


def validate_foundation(repo_root: Path) -> list[str]:
    config_root = repo_root / "config"
    errors: list[str] = []
    validators = [
        ("ownership-manifest.json", validate_ownership_manifest),
        ("provider-policy.json", validate_provider_policy),
        ("import-policy.json", validate_import_policy),
        ("information-classes.json", validate_information_classes),
        ("orchestration-boundary.json", validate_orchestration_boundary),
    ]
    for filename, validator in validators:
        try:
            data = load_json(config_root / filename)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(validator(data))
    try:
        from .embedding_models import load_embedding_model_catalog

        load_embedding_model_catalog(repo_root)
    except (ImportError, ValueError) as exc:
        errors.append(f"embedding model catalog is invalid: {exc}")
    try:
        from .model_routing import load_model_routing_policy

        load_model_routing_policy(repo_root)
    except (ImportError, ValueError) as exc:
        errors.append(f"model routing policy is invalid: {exc}")
    try:
        from .project_capability_profile import (
            load_project_capability_profiler_policy,
        )

        load_project_capability_profiler_policy(repo_root)
    except (ImportError, ValueError) as exc:
        errors.append(f"project capability profiler policy is invalid: {exc}")
    try:
        from .work_semantic_index import load_work_retrieval_policy

        load_work_retrieval_policy(repo_root)
    except (ImportError, ValueError) as exc:
        errors.append(f"work retrieval policy is invalid: {exc}")
    try:
        from .work_index import load_work_index_policy

        load_work_index_policy(repo_root)
    except (ImportError, ValueError) as exc:
        errors.append(f"work index policy is invalid: {exc}")
    return errors


def _is_blocked_path(relative_path: str, patterns: Sequence[str]) -> bool:
    normalized = relative_path.replace("\\", "/")
    candidates = {normalized, f"x/{normalized}"}
    return any(
        fnmatch.fnmatch(candidate, pattern)
        for candidate in candidates
        for pattern in patterns
    )


def detect_content_findings(
    text: str,
    relative_path: str,
    detectors: set[str],
) -> list[Finding]:
    """Return detector identities without disclosing matched source values."""

    findings: list[Finding] = []
    regex_detectors = {
        "windows-absolute-path": re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:\\"),
        "posix-user-path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
        "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "github-token": re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"),
        "aws-access-key": re.compile(r"AKIA[0-9A-Z]{16}"),
        "generic-secret-assignment": re.compile(
            r"(?im)^\s*[\"']?(?:[A-Za-z0-9_.-]+[.-])?"
            r"(?:password|passwd|token|api[_-]?key|secret|client[_-]?secret|access[_-]?token)"
            r"[\"']?\s*[:=]\s*[\"']?"
            r"(?!\$\{|\$[A-Za-z_]|env://|keyring://|secret://|<|\{\{)"
            r"[A-Za-z0-9+/=_-]{8,}"
        ),
        "credential-uri": re.compile(
            r"(?i)\b[a-z][a-z0-9+.-]{1,20}://[^\s/:@]+:[^\s/@]{4,}@"
        ),
        "email-address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "unicode-long-dash": re.compile("[\u2013\u2014]"),
    }
    for detector_id, pattern in regex_detectors.items():
        if detector_id in detectors and pattern.search(text):
            findings.append(Finding(detector_id, relative_path, "prohibited content detected"))

    if "ip-address" in detectors:
        for match in re.finditer(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", text):
            try:
                ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            findings.append(Finding("ip-address", relative_path, "prohibited content detected"))
            break
    return findings


def scan_paths(root: Path, paths: Iterable[Path], policy: dict) -> list[Finding]:
    findings: list[Finding] = []
    blocked_globs = policy["blocked_globs"]
    detectors = set(policy["content_detectors"])
    maximum_bytes = policy["maximum_text_file_bytes"]

    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _is_blocked_path(relative, blocked_globs):
            findings.append(Finding("blocked-path", relative, "path is prohibited by import policy"))
            continue
        if path.stat().st_size > maximum_bytes:
            findings.append(Finding("file-too-large", relative, f"file exceeds {maximum_bytes} bytes"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("non-utf8", relative, "text file is not valid UTF-8"))
            continue
        findings.extend(detect_content_findings(text, relative, detectors))
    return findings


def scan_tree(root: Path, policy: dict) -> list[Finding]:
    return scan_paths(root, (path for path in root.rglob("*") if path.is_file()), policy)


def git_candidate_paths(repo_root: Path) -> list[Path]:
    command = [
        "git",
        "-C",
        str(repo_root),
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return [
        repo_root / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]


def validate_json_documents(
    repo_root: Path,
    paths: Iterable[Path],
) -> list[Finding]:
    """Require readable, deterministic formatting for repository JSON files."""

    findings: list[Finding] = []
    for path in sorted(path for path in paths if path.suffix.casefold() == ".json"):
        relative = path.relative_to(repo_root).as_posix()
        try:
            document = path.read_bytes()
            payload = parse_json_bytes(document, label=relative)
            expected = pretty_json_bytes(payload, sort_keys=False)
        except (JsonDocumentError, OSError):
            findings.append(Finding("json-syntax", relative, "JSON document is invalid"))
            continue
        if document != expected:
            findings.append(
                Finding(
                    "json-format",
                    relative,
                    "JSON document must use the repository readable format",
                )
            )
    return findings


def verify_repository(repo_root: Path) -> list[Finding]:
    policy = load_json(repo_root / "config" / "import-policy.json")
    candidates = git_candidate_paths(repo_root)
    findings = [
        Finding("foundation-config", "config", error)
        for error in validate_foundation(repo_root)
    ]
    findings.extend(scan_paths(repo_root, candidates, policy))
    findings.extend(validate_json_documents(repo_root, candidates))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate KRCN Core foundation and import boundaries")
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root to verify",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Optional source directory to scan as an import candidate",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo.resolve()
    try:
        if args.source:
            policy = load_json(repo_root / "config" / "import-policy.json")
            findings = scan_tree(args.source.resolve(), policy)
        else:
            findings = verify_repository(repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if findings:
        for finding in findings:
            print(finding.render())
        return 1
    print("KRCN Core foundation verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

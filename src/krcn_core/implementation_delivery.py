"""Exact, rollback-safe delivery of reviewed sandbox patches."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping, Protocol, Sequence

from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .worktree_sandbox import SandboxPatchArtifact, parse_sandbox_patch_artifact


SHA = re.compile(r"^[a-f0-9]{64}$")
OID = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")


class ImplementationDeliveryError(ValueError):
    """Raised when implementation evidence, authority, or repository state is invalid."""


class ImplementationTestRunner(Protocol):
    def run(self, repo_root: Path, test_id: str, command_digest: str) -> Mapping[str, object]: ...


class ImplementationDeliveryHost(Protocol):
    def report_bytes(self, report_ref: str) -> bytes: ...
    def patch_artifact(self, artifact_id: str) -> SandboxPatchArtifact: ...
    def test_runner(self) -> ImplementationTestRunner: ...


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ImplementationDeliveryError(f"{label} must be a SHA-256 digest")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ImplementationDeliveryError(f"{label} must be portable")
    return value


def _ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ImplementationDeliveryError(f"{label} must be a portable reference")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts:
        raise ImplementationDeliveryError(f"{label} escapes the repository")
    return path.as_posix()


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], input=input_bytes, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=60,
    )
    if completed.returncode != 0:
        raise ImplementationDeliveryError("safe Git operation failed")
    return completed.stdout


def _identity(repo: Path) -> tuple[str, str]:
    root = Path(_git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if root != repo.resolve():
        raise ImplementationDeliveryError("target must be the Git repository root")
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    if not OID.fullmatch(head) or not OID.fullmatch(tree):
        raise ImplementationDeliveryError("Git identity is invalid")
    return head, tree


@dataclass(frozen=True)
class ImplementationPlan:
    payload: Mapping[str, object]
    mutation_plans: tuple[MutationPlan, ...] = field(repr=False)
    repo_root: Path = field(repr=False)

    @property
    def plan_id(self) -> str:
        return str(self.payload["plan_id"])

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


@dataclass(frozen=True)
class ImplementationResult:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


@dataclass(frozen=True)
class ImplementationVerification:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


def parse_implementation_result(value: object) -> ImplementationResult:
    required = {"schema_ref", "schema_version", "result_id", "plan_id", "project_id", "work_item_id", "task_plan_id", "patch_digest", "changed_paths", "test_results", "status", "rollback_available", "commit_created", "push_performed", "completion_allowed", "authority_granted", "result_digest"}
    if not isinstance(value, Mapping) or set(value) != required or value["schema_ref"] != "schemas/implementation-result.schema.json" or value["schema_version"] != 1:
        raise ImplementationDeliveryError("implementation result fields are invalid")
    for name in ("result_id", "plan_id", "task_plan_id", "patch_digest", "result_digest"):
        _sha(value[name], name)
    identity = {key: value[key] for key in required - {"schema_ref", "schema_version", "result_id", "result_digest"}}
    digest = _digest(identity)
    if value["result_id"] != digest or value["result_digest"] != digest or value["status"] != "pending-verification" or value["completion_allowed"] is not False or value["authority_granted"] is not False:
        raise ImplementationDeliveryError("implementation result digest or safety state is invalid")
    return ImplementationResult(dict(value))


def prepare_implementation_plan(
    repo_root: Path,
    resolver: OwnershipResolver,
    *,
    project_id: str,
    work_item_id: str,
    task_plan_id: str,
    report_ref: str,
    report_bytes: bytes,
    artifact: SandboxPatchArtifact,
    test_specs: Sequence[Mapping[str, object]],
    execution_trace_ref: str,
) -> ImplementationPlan:
    repo_root = repo_root.resolve()
    project_id = _id(project_id, "project id")
    work_item_id = _id(work_item_id, "work item id")
    task_plan_id = _sha(task_plan_id, "task plan id")
    report_ref = _ref(report_ref, "report ref")
    execution_trace_ref = _ref(execution_trace_ref, "execution trace ref")
    if not isinstance(report_bytes, bytes) or not report_bytes:
        raise ImplementationDeliveryError("report evidence is required")
    parsed_artifact = parse_sandbox_patch_artifact(artifact.as_dict())
    if artifact.patch_bytes and hashlib.sha256(artifact.patch_bytes).hexdigest() != parsed_artifact.payload["patch_digest"]:
        raise ImplementationDeliveryError("patch bytes do not match the sandbox artifact")
    head, tree = _identity(repo_root)
    if head != parsed_artifact.payload["source_head"] or tree != parsed_artifact.payload["source_tree_digest"]:
        raise ImplementationDeliveryError("sandbox artifact does not match the target revision")
    tests: list[dict[str, str]] = []
    for raw in test_specs:
        if not isinstance(raw, Mapping) or set(raw) != {"test_id", "command_digest"}:
            raise ImplementationDeliveryError("test specification fields are invalid")
        tests.append({"test_id": _id(raw["test_id"], "test id"), "command_digest": _sha(raw["command_digest"], "command digest")})
    tests.sort(key=lambda item: item["test_id"])
    if not tests or len({item["test_id"] for item in tests}) != len(tests):
        raise ImplementationDeliveryError("at least one unique allowlisted test is required")
    mutation_plans: list[MutationPlan] = []
    changed_paths: list[str] = []
    for item in parsed_artifact.payload["changed_files"]:
        path_ref = _ref(item["path_ref"], "changed path")
        changed_paths.append(path_ref)
        exists = (repo_root / PurePosixPath(path_ref)).exists()
        operation = "delete" if item["deleted"] else ("update" if exists else "create")
        change_digest = item["content_digest"] or hashlib.sha256(("delete:" + path_ref).encode()).hexdigest()
        mutation_plans.append(plan_mutation(resolver, operation=operation, target_ref=path_ref, change_digest=change_digest, reversible=True))
    if not changed_paths:
        raise ImplementationDeliveryError("empty patches cannot become implementation plans")
    identity = {
        "project_id": project_id, "work_item_id": work_item_id, "task_plan_id": task_plan_id,
        "report_ref": report_ref, "report_digest": hashlib.sha256(report_bytes).hexdigest(),
        "source_head": head, "source_tree_digest": tree, "sandbox_artifact_id": parsed_artifact.payload["artifact_id"],
        "patch_digest": parsed_artifact.payload["patch_digest"], "changed_paths": changed_paths,
        "test_specs": tests, "mutation_plan_ids": [item.plan_id for item in mutation_plans],
        "execution_trace_ref": execution_trace_ref, "plan_is_read_only": True,
        "commit_allowed": False, "push_allowed": False, "authority_granted": False,
    }
    plan_id = _digest(identity)
    payload = {"schema_ref": "schemas/implementation-plan.schema.json", "schema_version": 1, "plan_id": plan_id, **identity, "plan_digest": plan_id}
    return ImplementationPlan(payload, tuple(mutation_plans), repo_root)


def apply_implementation_plan(
    plan: ImplementationPlan,
    artifact: SandboxPatchArtifact,
    authorizations: Mapping[str, MutationAuthorization],
    *,
    expected_plan_id: str,
    current_report_bytes: bytes,
    test_runner: ImplementationTestRunner,
) -> ImplementationResult:
    if expected_plan_id != plan.plan_id:
        raise ImplementationDeliveryError("exact implementation plan id is required")
    head, tree = _identity(plan.repo_root)
    if head != plan.payload["source_head"] or tree != plan.payload["source_tree_digest"]:
        raise ImplementationDeliveryError("target repository changed after planning")
    if hashlib.sha256(current_report_bytes).hexdigest() != plan.payload["report_digest"]:
        raise ImplementationDeliveryError("implementation report changed after planning")
    if artifact.payload["artifact_id"] != plan.payload["sandbox_artifact_id"] or hashlib.sha256(artifact.patch_bytes).hexdigest() != plan.payload["patch_digest"]:
        raise ImplementationDeliveryError("exact process-local sandbox patch is required")
    for mutation in plan.mutation_plans:
        authorization = authorizations.get(mutation.plan_id)
        if authorization is None or authorization.plan != mutation or not authorization.dry_run_verified or (mutation.approval_required and not authorization.approval_verified):
            raise ImplementationDeliveryError("every changed path requires exact mutation authorization")
    patch = artifact.patch_bytes
    _git(plan.repo_root, "apply", "--check", "--binary", "-", input_bytes=patch)
    _git(plan.repo_root, "apply", "--binary", "-", input_bytes=patch)
    test_results: list[dict[str, object]] = []
    try:
        for spec in plan.payload["test_specs"]:
            outcome = test_runner.run(plan.repo_root, str(spec["test_id"]), str(spec["command_digest"]))
            if not isinstance(outcome, Mapping) or set(outcome) != {"passed", "evidence_digest"} or not isinstance(outcome["passed"], bool):
                raise ImplementationDeliveryError("test runner returned an invalid result")
            evidence = _sha(outcome["evidence_digest"], "test evidence digest")
            test_results.append({"test_id": spec["test_id"], "passed": outcome["passed"], "evidence_digest": evidence})
            if not outcome["passed"]:
                raise ImplementationDeliveryError("allowlisted implementation test failed")
    except Exception:
        _git(plan.repo_root, "apply", "--reverse", "--check", "--binary", "-", input_bytes=patch)
        _git(plan.repo_root, "apply", "--reverse", "--binary", "-", input_bytes=patch)
        raise
    result_identity = {
        "plan_id": plan.plan_id, "project_id": plan.payload["project_id"], "work_item_id": plan.payload["work_item_id"],
        "task_plan_id": plan.payload["task_plan_id"], "patch_digest": plan.payload["patch_digest"],
        "changed_paths": plan.payload["changed_paths"], "test_results": test_results,
        "status": "pending-verification", "rollback_available": True, "commit_created": False,
        "push_performed": False, "completion_allowed": False, "authority_granted": False,
    }
    digest = _digest(result_identity)
    return ImplementationResult({"schema_ref": "schemas/implementation-result.schema.json", "schema_version": 1, "result_id": digest, **result_identity, "result_digest": digest})


def verify_implementation_result(
    plan: ImplementationPlan,
    result: ImplementationResult,
    *,
    verifier_identity_digest: str,
    verifier_evidence_digest: str,
) -> ImplementationVerification:
    verifier_identity_digest = _sha(verifier_identity_digest, "verifier identity digest")
    verifier_evidence_digest = _sha(verifier_evidence_digest, "verifier evidence digest")
    if result.payload["plan_id"] != plan.plan_id or result.payload["status"] != "pending-verification":
        raise ImplementationDeliveryError("implementation result is not verifiable")
    identity = {
        "plan_id": plan.plan_id, "result_id": result.payload["result_id"],
        "verifier_identity_digest": verifier_identity_digest, "verifier_evidence_digest": verifier_evidence_digest,
        "status": "verified", "completion_allowed": True, "authority_granted": False,
    }
    digest = _digest(identity)
    return ImplementationVerification({"schema_ref": "schemas/implementation-verification.schema.json", "schema_version": 1, "verification_id": digest, **identity, "verification_digest": digest})

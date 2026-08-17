"""Exact-revision detached worktree sandbox contracts and safe Git adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping, Sequence

from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
SHA = re.compile(r"^[a-f0-9]{64}$")
GIT_OID = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


class WorktreeSandboxError(ValueError):
    """Raised when a sandbox boundary is incomplete or stale."""


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise WorktreeSandboxError(f"{label} must be a SHA-256 digest")
    return value


def _oid(value: object, label: str) -> str:
    if not isinstance(value, str) or not GIT_OID.fullmatch(value):
        raise WorktreeSandboxError(f"{label} must be a Git object id")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise WorktreeSandboxError(f"{label} must be portable")
    return value


def _relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise WorktreeSandboxError(f"{label} must be a portable relative path")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if path.is_absolute() or windows.is_absolute() or ".." in path.parts or value.startswith("//"):
        raise WorktreeSandboxError(f"{label} escapes the repository")
    return path.as_posix()


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


def _safe_ancestors(path: Path, boundary: Path) -> None:
    boundary = boundary.resolve()
    candidate = path.absolute()
    try:
        candidate.relative_to(boundary)
    except ValueError as exc:
        raise WorktreeSandboxError("sandbox path escapes its runtime boundary") from exc
    current = boundary
    for part in candidate.relative_to(boundary).parts:
        current = current / part
        if current.exists() and (current.is_symlink() or _is_junction(current)):
            raise WorktreeSandboxError("sandbox path uses a symlink or junction ancestor")
    existing = candidate
    while not existing.exists() and existing != boundary:
        existing = existing.parent
    try:
        existing.resolve().relative_to(boundary)
    except ValueError as exc:
        raise WorktreeSandboxError("resolved sandbox path escapes its runtime boundary") from exc


def _git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise WorktreeSandboxError("safe Git operation failed")
    return completed.stdout


def _git_identity(repo: Path) -> tuple[str, str]:
    top = Path(_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if top != repo.resolve():
        raise WorktreeSandboxError("sandbox source must be the Git repository root")
    head = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    return _oid(head, "Git HEAD"), _oid(tree, "Git tree")


@dataclass(frozen=True)
class SandboxHostProfile:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))

    @property
    def execution_allowed(self) -> bool:
        return bool(self.payload["execution_allowed"])


@dataclass(frozen=True)
class WorktreeSandboxPlan:
    payload: Mapping[str, object]
    mutation_plan: MutationPlan = field(repr=False)
    repo_root: Path = field(repr=False)

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))

    @property
    def plan_id(self) -> str:
        return str(self.payload["sandbox_plan_id"])


@dataclass(frozen=True)
class SandboxPatchArtifact:
    payload: Mapping[str, object]
    patch_bytes: bytes = field(repr=False)

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


def build_sandbox_host_profile(
    *,
    host_id: str,
    os_family: str,
    detached_worktree: bool,
    path_isolation: bool,
    environment_allowlist: bool,
    network_default_deny: bool,
    commit_push_blocked: bool,
    junction_guard: bool,
) -> SandboxHostProfile:
    host_id = _id(host_id, "sandbox host id")
    if os_family not in {"windows", "linux", "macos"}:
        raise WorktreeSandboxError("sandbox host OS is invalid")
    flags = {
        "detached_worktree": detached_worktree,
        "path_isolation": path_isolation,
        "environment_allowlist": environment_allowlist,
        "network_default_deny": network_default_deny,
        "commit_push_blocked": commit_push_blocked,
        "junction_guard": junction_guard,
    }
    if any(not isinstance(value, bool) for value in flags.values()):
        raise WorktreeSandboxError("sandbox host capabilities must be boolean")
    allowed = all(flags.values())
    identity = {
        "host_id": host_id,
        "os_family": os_family,
        **flags,
        "execution_allowed": allowed,
        "authority_granted": False,
    }
    digest = _digest(identity)
    return SandboxHostProfile({
        "schema_ref": "schemas/sandbox-host-profile.schema.json",
        "schema_version": 1,
        **identity,
        "profile_digest": digest,
    })


def parse_sandbox_host_profile(value: object) -> SandboxHostProfile:
    fields = {
        "schema_ref", "schema_version", "host_id", "os_family",
        "detached_worktree", "path_isolation", "environment_allowlist",
        "network_default_deny", "commit_push_blocked", "junction_guard",
        "execution_allowed", "authority_granted", "profile_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise WorktreeSandboxError("sandbox host profile fields are invalid")
    expected = build_sandbox_host_profile(
        host_id=str(value["host_id"]), os_family=str(value["os_family"]),
        detached_worktree=value["detached_worktree"], path_isolation=value["path_isolation"],
        environment_allowlist=value["environment_allowlist"],
        network_default_deny=value["network_default_deny"],
        commit_push_blocked=value["commit_push_blocked"], junction_guard=value["junction_guard"],
    )
    if value["schema_ref"] != "schemas/sandbox-host-profile.schema.json" or value["schema_version"] != 1:
        raise WorktreeSandboxError("sandbox host schema identity is invalid")
    if value["profile_digest"] != expected.payload["profile_digest"] or value["execution_allowed"] != expected.execution_allowed or value["authority_granted"] is not False:
        raise WorktreeSandboxError("sandbox host profile digest is invalid")
    return expected


def prepare_worktree_sandbox(
    repo_root: Path,
    resolver: OwnershipResolver,
    *,
    project_id: str,
    task_plan_id: str,
    worker_step_id: str,
    validation_gate_id: str,
    effect_claim_id: str,
    allowed_paths: Sequence[str],
    allowed_executables: Sequence[str],
    allowed_env_keys: Sequence[str],
    host_profile: SandboxHostProfile | Mapping[str, object],
    network_authorization_digest: str | None = None,
    maximum_patch_bytes: int = 8388608,
) -> WorktreeSandboxPlan:
    project_id = _id(project_id, "project id")
    worker_step_id = _id(worker_step_id, "worker step id")
    task_plan_id = _sha(task_plan_id, "task plan id")
    validation_gate_id = _sha(validation_gate_id, "validation gate id")
    effect_claim_id = _sha(effect_claim_id, "effect claim id")
    profile = parse_sandbox_host_profile(host_profile.as_dict() if isinstance(host_profile, SandboxHostProfile) else host_profile)
    paths = tuple(sorted(_relative(item, "allowed path") for item in allowed_paths))
    executables = tuple(sorted(_id(item, "allowed executable") for item in allowed_executables))
    env_keys = tuple(sorted(str(item) for item in allowed_env_keys))
    if not paths or len(set(path.lower() for path in paths)) != len(paths):
        raise WorktreeSandboxError("allowed paths are empty or case-colliding")
    if not executables or len(set(executables)) != len(executables):
        raise WorktreeSandboxError("allowed executables are invalid")
    if len(set(env_keys)) != len(env_keys) or any(not ENV_KEY.fullmatch(item) for item in env_keys):
        raise WorktreeSandboxError("allowed environment keys are invalid")
    if network_authorization_digest is not None:
        _sha(network_authorization_digest, "network authorization digest")
    if isinstance(maximum_patch_bytes, bool) or not isinstance(maximum_patch_bytes, int) or not 1 <= maximum_patch_bytes <= 16777216:
        raise WorktreeSandboxError("maximum patch bytes is invalid")
    head, tree = _git_identity(repo_root)
    semantic = {
        "project_id": project_id,
        "task_plan_id": task_plan_id,
        "worker_step_id": worker_step_id,
        "validation_gate_id": validation_gate_id,
        "effect_claim_id": effect_claim_id,
        "source_head": head,
        "source_tree_digest": tree,
        "allowed_paths": list(paths),
        "allowed_executables": list(executables),
        "allowed_env_keys": list(env_keys),
        "network_authorization_digest": network_authorization_digest,
        "network_default_deny": network_authorization_digest is None,
        "commit_push_allowed": False,
        "maximum_patch_bytes": maximum_patch_bytes,
        "host_profile_digest": profile.payload["profile_digest"],
        "execution_allowed": profile.execution_allowed,
        "contains_physical_paths": False,
        "grants_authority": False,
    }
    plan_id = _digest(semantic)
    mutation = plan_mutation(
        resolver, operation="create",
        target_ref=f".krcn/projects/{project_id}/runtime/sandboxes/{plan_id}",
        expected_ownership="runtime", change_digest=plan_id, reversible=True,
    )
    payload = {
        "schema_ref": "schemas/worktree-sandbox-plan.schema.json",
        "schema_version": 1,
        "sandbox_plan_id": plan_id,
        **semantic,
        "mutation_plan_id": mutation.plan_id,
        "plan_digest": "",
    }
    payload["plan_digest"] = _digest({key: value for key, value in payload.items() if key not in {"schema_ref", "schema_version", "plan_digest"}})
    return parse_worktree_sandbox_plan(payload, mutation_plan=mutation, repo_root=repo_root)


def parse_worktree_sandbox_plan(
    value: object, *, mutation_plan: MutationPlan, repo_root: Path
) -> WorktreeSandboxPlan:
    fields = {
        "schema_ref", "schema_version", "sandbox_plan_id", "project_id",
        "task_plan_id", "worker_step_id", "validation_gate_id", "effect_claim_id",
        "source_head", "source_tree_digest", "allowed_paths", "allowed_executables",
        "allowed_env_keys", "network_authorization_digest", "network_default_deny",
        "commit_push_allowed", "host_profile_digest", "execution_allowed",
        "maximum_patch_bytes", "contains_physical_paths", "grants_authority", "mutation_plan_id", "plan_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise WorktreeSandboxError("worktree sandbox plan fields are invalid")
    if value["schema_ref"] != "schemas/worktree-sandbox-plan.schema.json" or value["schema_version"] != 1:
        raise WorktreeSandboxError("worktree sandbox schema identity is invalid")
    _id(value["project_id"], "project id")
    _id(value["worker_step_id"], "worker step id")
    for field_name in ("sandbox_plan_id", "task_plan_id", "validation_gate_id", "effect_claim_id", "host_profile_digest", "mutation_plan_id", "plan_digest"):
        _sha(value[field_name], field_name)
    _oid(value["source_head"], "source head")
    _oid(value["source_tree_digest"], "source tree")
    paths = value["allowed_paths"]
    executables = value["allowed_executables"]
    env_keys = value["allowed_env_keys"]
    if not isinstance(paths, list) or not paths or paths != sorted(paths) or len(set(str(item).lower() for item in paths)) != len(paths):
        raise WorktreeSandboxError("sandbox allowed paths are invalid")
    for item in paths:
        _relative(item, "allowed path")
    if not isinstance(executables, list) or not executables or executables != sorted(executables) or len(set(executables)) != len(executables):
        raise WorktreeSandboxError("sandbox executables are invalid")
    for item in executables:
        _id(item, "allowed executable")
    if not isinstance(env_keys, list) or env_keys != sorted(env_keys) or len(set(env_keys)) != len(env_keys) or any(not ENV_KEY.fullmatch(str(item)) for item in env_keys):
        raise WorktreeSandboxError("sandbox environment keys are invalid")
    network_digest = value["network_authorization_digest"]
    if network_digest is not None:
        _sha(network_digest, "network authorization digest")
    if value["network_default_deny"] is not (network_digest is None):
        raise WorktreeSandboxError("sandbox network policy is inconsistent")
    if value["commit_push_allowed"] is not False or value["contains_physical_paths"] is not False or value["grants_authority"] is not False or not isinstance(value["execution_allowed"], bool):
        raise WorktreeSandboxError("sandbox safety flags are invalid")
    maximum = value["maximum_patch_bytes"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 16777216:
        raise WorktreeSandboxError("sandbox patch limit is invalid")
    semantic = {key: value[key] for key in fields if key not in {"schema_ref", "schema_version", "sandbox_plan_id", "mutation_plan_id", "plan_digest"}}
    expected_id = _digest(semantic)
    expected_plan_digest = _digest({key: value[key] for key in fields if key not in {"schema_ref", "schema_version", "plan_digest"}})
    if value["sandbox_plan_id"] != expected_id or value["plan_digest"] != expected_plan_digest:
        raise WorktreeSandboxError("sandbox plan digest is invalid")
    if mutation_plan.plan_id != value["mutation_plan_id"] or mutation_plan.change_digest != expected_id or mutation_plan.ownership != "runtime":
        raise WorktreeSandboxError("sandbox mutation authorization binding is invalid")
    return WorktreeSandboxPlan(dict(value), mutation_plan, repo_root.resolve())


def create_detached_worktree(
    plan: WorktreeSandboxPlan,
    authorization: MutationAuthorization,
    *,
    sandbox_parent: Path,
) -> Path:
    if not plan.payload["execution_allowed"]:
        raise WorktreeSandboxError("sandbox host enforcement is insufficient")
    if authorization.plan.plan_id != plan.mutation_plan.plan_id or not authorization.dry_run_verified:
        raise WorktreeSandboxError("exact sandbox mutation authorization is required")
    head, tree = _git_identity(plan.repo_root)
    if head != plan.payload["source_head"] or tree != plan.payload["source_tree_digest"]:
        raise WorktreeSandboxError("sandbox source revision is stale")
    parent = sandbox_parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    _safe_ancestors(parent, parent)
    target = parent / str(plan.payload["sandbox_plan_id"])
    _safe_ancestors(target, parent)
    if target.exists():
        raise WorktreeSandboxError("sandbox target already exists")
    completed = subprocess.run(
        ["git", "-C", str(plan.repo_root), "worktree", "add", "--detach", str(target), head],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60,
    )
    if completed.returncode != 0:
        raise WorktreeSandboxError("detached worktree creation failed")
    try:
        target_head, target_tree = _git_identity(target)
        if target_head != head or target_tree != tree:
            raise WorktreeSandboxError("created worktree identity is invalid")
        return target
    except Exception:
        subprocess.run(["git", "-C", str(plan.repo_root), "worktree", "remove", "--force", str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        raise


def collect_patch_artifact(
    plan: WorktreeSandboxPlan,
    sandbox_path: Path,
    *,
    effect_receipt_id: str,
    verifier_evidence_digest: str,
) -> SandboxPatchArtifact:
    effect_receipt_id = _sha(effect_receipt_id, "effect receipt id")
    verifier_evidence_digest = _sha(verifier_evidence_digest, "verifier evidence digest")
    sandbox_path = sandbox_path.resolve()
    head, _ = _git_identity(sandbox_path)
    if head != plan.payload["source_head"]:
        raise WorktreeSandboxError("sandbox commit drift is prohibited")
    status = _git(sandbox_path, "status", "--porcelain=v1", "-z")
    entries = [entry for entry in status.decode("utf-8").split("\x00") if entry]
    paths: list[str] = []
    for entry in entries:
        if len(entry) < 4:
            raise WorktreeSandboxError("sandbox status entry is invalid")
        path_text = entry[3:]
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        paths.append(_relative(path_text, "changed path"))
    normalized = sorted(set(paths))
    allowed = tuple(str(item) for item in plan.payload["allowed_paths"])
    for changed in normalized:
        if not any(changed == item or changed.startswith(item.rstrip("/") + "/") for item in allowed):
            raise WorktreeSandboxError("sandbox changed path is outside the allowlist")
        candidate = sandbox_path / PurePosixPath(changed)
        if candidate.exists() and (candidate.is_symlink() or _is_junction(candidate)):
            raise WorktreeSandboxError("sandbox changed path is a symlink or junction")
        if candidate.exists():
            try:
                candidate.resolve().relative_to(sandbox_path)
            except ValueError as exc:
                raise WorktreeSandboxError("sandbox changed path escapes worktree") from exc
    untracked = [entry[3:] for entry in entries if entry.startswith("?? ")]
    if untracked:
        _git(sandbox_path, "add", "-N", "--", *untracked)
    patch = _git(sandbox_path, "diff", "--binary", "--no-ext-diff", "--", *normalized) if normalized else b""
    if len(patch) > int(plan.payload["maximum_patch_bytes"]):
        raise WorktreeSandboxError("sandbox patch exceeds the bounded output limit")
    patch_digest = hashlib.sha256(patch).hexdigest()
    files = []
    for changed in normalized:
        candidate = sandbox_path / PurePosixPath(changed)
        files.append({
            "path_ref": changed,
            "content_digest": hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.is_file() else None,
            "deleted": not candidate.exists(),
        })
    identity = {
        "sandbox_plan_id": plan.plan_id,
        "source_head": plan.payload["source_head"],
        "source_tree_digest": plan.payload["source_tree_digest"],
        "effect_claim_id": plan.payload["effect_claim_id"],
        "effect_receipt_id": effect_receipt_id,
        "validation_gate_id": plan.payload["validation_gate_id"],
        "verifier_evidence_digest": verifier_evidence_digest,
        "changed_files": files,
        "patch_digest": patch_digest,
        "contains_patch_bytes": False,
        "commit_created": False,
        "push_performed": False,
        "grants_authority": False,
    }
    artifact_digest = _digest(identity)
    payload = {
        "schema_ref": "schemas/sandbox-patch-artifact.schema.json",
        "schema_version": 1,
        "artifact_id": artifact_digest,
        **identity,
        "artifact_digest": artifact_digest,
    }
    return SandboxPatchArtifact(payload, patch)


def parse_sandbox_patch_artifact(value: object) -> SandboxPatchArtifact:
    fields = {
        "schema_ref", "schema_version", "artifact_id", "sandbox_plan_id",
        "source_head", "source_tree_digest", "effect_claim_id", "effect_receipt_id",
        "validation_gate_id", "verifier_evidence_digest", "changed_files",
        "patch_digest", "contains_patch_bytes", "commit_created", "push_performed",
        "grants_authority", "artifact_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise WorktreeSandboxError("sandbox patch artifact fields are invalid")
    if value["schema_ref"] != "schemas/sandbox-patch-artifact.schema.json" or value["schema_version"] != 1:
        raise WorktreeSandboxError("sandbox patch artifact schema identity is invalid")
    for name in ("artifact_id", "sandbox_plan_id", "effect_claim_id", "effect_receipt_id", "validation_gate_id", "verifier_evidence_digest", "patch_digest", "artifact_digest"):
        _sha(value[name], name)
    _oid(value["source_head"], "source head")
    _oid(value["source_tree_digest"], "source tree")
    if value["contains_patch_bytes"] is not False or value["commit_created"] is not False or value["push_performed"] is not False or value["grants_authority"] is not False:
        raise WorktreeSandboxError("sandbox patch artifact safety flags are invalid")
    changed = value["changed_files"]
    if not isinstance(changed, list):
        raise WorktreeSandboxError("sandbox changed files are invalid")
    observed: list[str] = []
    for item in changed:
        if not isinstance(item, Mapping) or set(item) != {"path_ref", "content_digest", "deleted"}:
            raise WorktreeSandboxError("sandbox changed file fields are invalid")
        observed.append(_relative(item["path_ref"], "changed path"))
        if not isinstance(item["deleted"], bool):
            raise WorktreeSandboxError("sandbox deletion flag is invalid")
        if item["content_digest"] is not None:
            _sha(item["content_digest"], "changed content digest")
        if item["deleted"] is (item["content_digest"] is not None):
            raise WorktreeSandboxError("sandbox changed file state is inconsistent")
    if observed != sorted(set(observed)):
        raise WorktreeSandboxError("sandbox changed files are not canonical")
    identity = {key: value[key] for key in fields - {"schema_ref", "schema_version", "artifact_id", "artifact_digest"}}
    digest = _digest(identity)
    if value["artifact_id"] != digest or value["artifact_digest"] != digest:
        raise WorktreeSandboxError("sandbox patch artifact digest is invalid")
    return SandboxPatchArtifact(dict(value), b"")


def remove_detached_worktree(plan: WorktreeSandboxPlan, sandbox_path: Path) -> None:
    sandbox_path = sandbox_path.resolve()
    if sandbox_path.name != plan.plan_id:
        raise WorktreeSandboxError("sandbox cleanup identity is invalid")
    completed = subprocess.run(
        ["git", "-C", str(plan.repo_root), "worktree", "remove", "--force", str(sandbox_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60,
    )
    if completed.returncode != 0:
        raise WorktreeSandboxError("sandbox cleanup failed")

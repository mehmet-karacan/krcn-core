"""Exact-plan initialization of one project-scoped KRCN home."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .project_home import PROJECT_HOME_MANIFEST, ProjectHomeResolution


MANIFEST_NAME = PROJECT_HOME_MANIFEST
MANIFEST_SCHEMA = "schemas/project-home-manifest.schema.json"
LAYOUT_VERSION = 2
MAX_GIT_EXCLUDE_BYTES = 1_000_000


class ProjectHomeInitializationError(ValueError):
    """Raised when project-home initialization cannot remain exact and safe."""


@dataclass(frozen=True)
class GitExclusionPlan:
    git_root: Path
    exclude_path: Path
    relative_home: str
    ignore_pattern: str
    previous_content: bytes
    next_content: bytes
    mutation: MutationPlan

    def public_summary(self, *, disclose_path: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "path_disclosed": disclose_path,
            "tracked_gitignore_changed": False,
            "mutation": self.mutation.as_dict(),
        }
        if disclose_path:
            result["relative_home"] = self.relative_home
            result["ignore_pattern"] = self.ignore_pattern
        return result


@dataclass(frozen=True)
class ProjectHomeInitializationPlan:
    plan_id: str
    resolution: ProjectHomeResolution
    home_id: str
    manifest_content: bytes
    home_mutation: MutationPlan | None
    git_exclusion: GitExclusionPlan | None
    already_initialized: bool

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        effects = []
        if self.git_exclusion is not None:
            effects.append(self.git_exclusion.mutation)
        if self.home_mutation is not None:
            effects.append(self.home_mutation)
        return tuple(effects)

    def public_summary(self, *, disclose_path: bool = False) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-home-initialization-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "resolution": self.resolution.as_dict(disclose_path=disclose_path),
            "home_id": self.home_id,
            "already_initialized": self.already_initialized,
            "source_copy": False,
            "local_data_in_git": False,
            "tracked_gitignore_changed": False,
            "git_exclusion": (
                self.git_exclusion.public_summary(disclose_path=disclose_path)
                if self.git_exclusion is not None
                else None
            ),
            "effect_plans": [item.as_dict() for item in self.effect_plans],
        }


@dataclass(frozen=True)
class ProjectHomeInitializationResult:
    plan_id: str
    home_id: str
    home_created: bool
    git_exclusion_updated: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "home_id": self.home_id,
            "home_created": self.home_created,
            "git_exclusion_updated": self.git_exclusion_updated,
            "source_copy": False,
            "local_data_in_git": False,
            "paths_disclosed": False,
        }


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest_content(project_root: Path, home: Path) -> tuple[str, bytes]:
    home_id = hashlib.sha256(
        (
            "krcn-project-home-v2:"
            + str(project_root.resolve())
            + ":"
            + str(home.resolve(strict=False))
        ).encode("utf-8")
    ).hexdigest()
    content = _canonical_json(
        {
            "schema_ref": MANIFEST_SCHEMA,
            "schema_version": 1,
            "layout_version": LAYOUT_VERSION,
            "home_id": home_id,
            "home_kind": "project",
            "project_scoped": True,
            "source_copy": False,
            "local_data_in_git": False,
        }
    )
    return home_id, content


def _parse_manifest(content: bytes) -> str:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectHomeInitializationError(
            "project-home manifest is unreadable"
        ) from exc
    expected = {
        "schema_ref",
        "schema_version",
        "layout_version",
        "home_id",
        "home_kind",
        "project_scoped",
        "source_copy",
        "local_data_in_git",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ProjectHomeInitializationError("project-home manifest fields are invalid")
    home_id = payload.get("home_id")
    if (
        payload.get("schema_ref") != MANIFEST_SCHEMA
        or payload.get("schema_version") != 1
        or payload.get("layout_version") != LAYOUT_VERSION
        or payload.get("home_kind") != "project"
        or payload.get("project_scoped") is not True
        or payload.get("source_copy") is not False
        or payload.get("local_data_in_git") is not False
        or not isinstance(home_id, str)
        or len(home_id) != 64
        or any(character not in "0123456789abcdef" for character in home_id)
    ):
        raise ProjectHomeInitializationError("project-home manifest is invalid")
    return home_id


def validate_project_home_manifest_content(content: bytes) -> str:
    """Validate portable project-home manifest bytes."""

    return _parse_manifest(content)


def validate_initialized_project_home(home: Path) -> str:
    """Validate one existing project-home marker without changing local state."""

    candidate = home.resolve(strict=False)
    if not candidate.is_dir() or candidate.is_symlink():
        raise ProjectHomeInitializationError(
            "project-home target must be a regular directory"
        )
    marker = candidate / MANIFEST_NAME
    if not marker.is_file() or marker.is_symlink():
        raise ProjectHomeInitializationError(
            "project-home manifest must be a regular file"
        )
    return validate_project_home_manifest_content(marker.read_bytes())


def _git(
    root: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


def _git_root(project_root: Path) -> Path | None:
    result = _git(project_root, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        raise ProjectHomeInitializationError("Git worktree root is unavailable")
    root = Path(value).resolve()
    try:
        project_root.relative_to(root)
    except ValueError as exc:
        raise ProjectHomeInitializationError(
            "project root is outside its reported Git worktree"
        ) from exc
    return root


def _read_exclude(path: Path) -> bytes:
    if path.exists() and path.is_symlink():
        raise ProjectHomeInitializationError("Git exclude file may not be a symbolic link")
    if not path.exists():
        return b""
    if not path.is_file():
        raise ProjectHomeInitializationError("Git exclude path must be a file")
    if path.stat().st_size > MAX_GIT_EXCLUDE_BYTES:
        raise ProjectHomeInitializationError("Git exclude file is unexpectedly large")
    return path.read_bytes()


def _append_ignore_pattern(content: bytes, pattern: str) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectHomeInitializationError("Git exclude file must be UTF-8") from exc
    existing = {line.strip() for line in text.splitlines()}
    if pattern in existing:
        return content
    prefix = "" if not text or text.endswith(("\n", "\r")) else "\n"
    return (text + prefix + pattern + "\n").encode("utf-8")


def _prepare_git_exclusion(
    project_root: Path,
    home: Path,
    ownership: OwnershipResolver,
) -> GitExclusionPlan | None:
    git_root = _git_root(project_root)
    if git_root is None:
        return None
    try:
        relative_home = home.relative_to(git_root).as_posix()
    except ValueError:
        return None
    tracked = _git(git_root, "ls-files", "-z", "--", relative_home)
    if tracked.returncode != 0:
        raise ProjectHomeInitializationError("Git tracking state is unavailable")
    if tracked.stdout:
        raise ProjectHomeInitializationError(
            "project-home content is already tracked by Git"
        )
    probe = f"{relative_home}/{MANIFEST_NAME}"
    ignored = _git(git_root, "check-ignore", "--no-index", "-q", "--", probe)
    if ignored.returncode == 0:
        return None
    if ignored.returncode != 1:
        raise ProjectHomeInitializationError("Git ignore state is unavailable")
    git_path = _git(git_root, "rev-parse", "--git-path", "info/exclude")
    if git_path.returncode != 0 or not git_path.stdout.strip():
        raise ProjectHomeInitializationError("Git exclude path is unavailable")
    exclude_path = Path(git_path.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = git_root / exclude_path
    exclude_path = exclude_path.resolve(strict=False)
    previous = _read_exclude(exclude_path)
    pattern = f"/{relative_home}/"
    following = _append_ignore_pattern(previous, pattern)
    if following == previous:
        return None
    mutation = plan_mutation(
        ownership,
        operation="update" if exclude_path.exists() else "create",
        target_ref="project-git/info-exclude",
        expected_ownership="unmanaged",
        change_digest=_sha256(following),
        reversible=True,
    )
    return GitExclusionPlan(
        git_root=git_root,
        exclude_path=exclude_path,
        relative_home=relative_home,
        ignore_pattern=pattern,
        previous_content=previous,
        next_content=following,
        mutation=mutation,
    )


def prepare_project_home_initialization(
    resolution: ProjectHomeResolution,
    ownership: OwnershipResolver,
) -> ProjectHomeInitializationPlan:
    """Inspect and freeze project-home initialization without writing anything."""

    if resolution.requires_user_choice:
        raise ProjectHomeInitializationError(
            "project-home location requires an explicit user choice"
        )
    home = resolution.path
    if home.exists() and (home.is_symlink() or not home.is_dir()):
        raise ProjectHomeInitializationError(
            "project-home target must be a regular directory"
        )
    if not home.exists():
        parent = home.parent
        if not parent.is_dir() or parent.is_symlink():
            raise ProjectHomeInitializationError(
                "project-home parent must be an existing regular directory"
            )
    git_exclusion = _prepare_git_exclusion(
        resolution.project_root,
        home,
        ownership,
    )
    generated_home_id, generated_content = _manifest_content(
        resolution.project_root,
        home,
    )
    marker = home / MANIFEST_NAME
    already_initialized = False
    home_id = generated_home_id
    manifest_content = generated_content
    home_mutation = None
    if home.exists():
        entries = tuple(home.iterdir())
        if marker.is_symlink():
            raise ProjectHomeInitializationError(
                "project-home manifest may not be a symbolic link"
            )
        if marker.exists():
            if not marker.is_file():
                raise ProjectHomeInitializationError(
                    "project-home manifest must be a file"
                )
            manifest_content = marker.read_bytes()
            home_id = _parse_manifest(manifest_content)
            already_initialized = True
        elif entries:
            raise ProjectHomeInitializationError(
                "existing project-home target is not an initialized KRCN home"
            )
    if not already_initialized:
        home_mutation = plan_mutation(
            ownership,
            operation="create",
            target_ref=f".krcn/{MANIFEST_NAME}",
            expected_ownership="user-data",
            change_digest=_sha256(manifest_content),
            reversible=True,
        )
    identity = {
        "project_root_sha256": hashlib.sha256(
            str(resolution.project_root).encode("utf-8")
        ).hexdigest(),
        "target_path_sha256": hashlib.sha256(str(home).encode("utf-8")).hexdigest(),
        "home_id": home_id,
        "manifest_sha256": _sha256(manifest_content),
        "already_initialized": already_initialized,
        "effect_plan_ids": [item.plan_id for item in (
            *((git_exclusion.mutation,) if git_exclusion is not None else ()),
            *((home_mutation,) if home_mutation is not None else ()),
        )],
    }
    plan_id = hashlib.sha256(_canonical_json(identity)).hexdigest()
    return ProjectHomeInitializationPlan(
        plan_id=plan_id,
        resolution=resolution,
        home_id=home_id,
        manifest_content=manifest_content,
        home_mutation=home_mutation,
        git_exclusion=git_exclusion,
        already_initialized=already_initialized,
    )


def _require_authorizations(
    plan: ProjectHomeInitializationPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    for mutation in plan.effect_plans:
        authorization = authorizations.get(mutation.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != mutation.plan_id
            or not authorization.dry_run_verified
            or not authorization.approval_verified
        ):
            raise ProjectHomeInitializationError(
                "every initialization effect requires matching authorization"
            )


def _atomic_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _restore_exclude(change: GitExclusionPlan) -> None:
    if change.mutation.operation == "update":
        _atomic_replace(change.exclude_path, change.previous_content)
    else:
        change.exclude_path.unlink(missing_ok=True)


def apply_git_exclusion(change: GitExclusionPlan) -> None:
    """Apply and verify one exact local Git exclusion effect."""

    if _read_exclude(change.exclude_path) != change.previous_content:
        raise ProjectHomeInitializationError(
            "Git exclude file changed before initialization"
        )
    _atomic_replace(change.exclude_path, change.next_content)
    probe = f"{change.relative_home}/{MANIFEST_NAME}"
    ignored = _git(
        change.git_root,
        "check-ignore",
        "--no-index",
        "-q",
        "--",
        probe,
    )
    if ignored.returncode != 0:
        _restore_exclude(change)
        raise ProjectHomeInitializationError(
            "project-home Git exclusion verification failed"
        )


def rollback_git_exclusion(change: GitExclusionPlan) -> None:
    """Restore the exact pre-plan Git exclusion bytes."""

    _restore_exclude(change)


def apply_project_home_initialization(
    plan: ProjectHomeInitializationPlan,
    authorizations: Mapping[str, MutationAuthorization],
    ownership: OwnershipResolver,
) -> ProjectHomeInitializationResult:
    """Apply one exact initialization plan and verify Git exclusion."""

    _require_authorizations(plan, authorizations)
    current = prepare_project_home_initialization(plan.resolution, ownership)
    if current.plan_id != plan.plan_id:
        raise ProjectHomeInitializationError(
            "project-home initialization plan changed before apply"
        )
    exclusion_updated = False
    home_created = False
    created_directory = False
    try:
        if plan.git_exclusion is not None:
            apply_git_exclusion(plan.git_exclusion)
            exclusion_updated = True
        if plan.home_mutation is not None:
            home = plan.resolution.path
            if not home.exists():
                home.mkdir()
                created_directory = True
            marker = home / MANIFEST_NAME
            with marker.open("xb") as stream:
                stream.write(plan.manifest_content)
                stream.flush()
                os.fsync(stream.fileno())
            home_created = True
        marker = plan.resolution.path / MANIFEST_NAME
        if marker.read_bytes() != plan.manifest_content:
            raise ProjectHomeInitializationError(
                "project-home manifest verification failed"
            )
    except (OSError, ProjectHomeInitializationError) as exc:
        if home_created:
            (plan.resolution.path / MANIFEST_NAME).unlink(missing_ok=True)
        if created_directory:
            try:
                plan.resolution.path.rmdir()
            except OSError:
                pass
        if exclusion_updated and plan.git_exclusion is not None:
            rollback_git_exclusion(plan.git_exclusion)
        if isinstance(exc, ProjectHomeInitializationError):
            raise
        raise ProjectHomeInitializationError(
            "project-home initialization could not be applied"
        ) from exc
    return ProjectHomeInitializationResult(
        plan_id=plan.plan_id,
        home_id=plan.home_id,
        home_created=home_created,
        git_exclusion_updated=exclusion_updated,
    )

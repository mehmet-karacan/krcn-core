"""Non-mutating resolution of one project-scoped KRCN home."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .user_home import KRCN_HOME_ENV


PROJECT_HOME_DIRECTORY = ".krcn"
PROJECT_HOME_MANIFEST = "project-home.json"
RESOLUTION_SOURCES = {
    "explicit",
    "environment",
    "remembered",
    "project-default",
    "user-selected",
}
RESOLUTION_STATUSES = {"choice-required", "selected-existing", "selected-new"}
CHOICES = ("use-default", "choose-parent", "cancel")


class ProjectHomeError(ValueError):
    """Raised when a project-home target is unsafe or ambiguous."""


@dataclass(frozen=True)
class ProjectHomeResolution:
    project_root: Path
    path: Path
    source: str
    status: str
    target_kind: str
    requires_user_choice: bool
    requires_initialization: bool
    git_check_required: bool
    choices: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self, *, disclose_path: bool = False) -> dict[str, object]:
        """Return a client-neutral summary with optional local path disclosure."""

        result: dict[str, object] = {
            "schema_ref": "schemas/project-home-resolution.schema.json",
            "schema_version": 1,
            "source": self.source,
            "status": self.status,
            "target_kind": self.target_kind,
            "requires_user_choice": self.requires_user_choice,
            "requires_initialization": self.requires_initialization,
            "git_check_required": self.git_check_required,
            "choices": list(self.choices),
            "warnings": list(self.warnings),
            "path_disclosed": disclose_path,
        }
        if disclose_path:
            result["target_path"] = str(self.path)
        return result


def _absolute_path(value: Path, label: str, *, must_exist: bool) -> Path:
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise ProjectHomeError(f"{label} must be an absolute path")
    if expanded.exists() and expanded.is_symlink():
        raise ProjectHomeError(f"{label} may not be a symbolic link")
    resolved = expanded.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise ProjectHomeError(f"{label} may not be a filesystem root")
    if must_exist and not resolved.exists():
        raise ProjectHomeError(f"{label} must exist")
    if resolved.exists() and not resolved.is_dir():
        raise ProjectHomeError(f"{label} must be a directory")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolution(
    project_root: Path,
    data_root: Path,
    *,
    source: str,
    requires_user_choice: bool,
) -> ProjectHomeResolution:
    if source not in RESOLUTION_SOURCES:
        raise ProjectHomeError("project-home resolution source is invalid")
    target = _absolute_path(data_root, "KRCN project home", must_exist=False)
    project_local = _is_within(target, project_root)
    if project_local and target.name != PROJECT_HOME_DIRECTORY:
        raise ProjectHomeError(
            "a project-local KRCN home must use the .krcn directory name"
        )
    status = (
        "choice-required"
        if requires_user_choice
        else "selected-existing" if target.exists() else "selected-new"
    )
    warnings = [
        "local-data-not-in-git",
        "git-clone-does-not-restore-local-data",
        "backup-required-for-recovery",
    ]
    if not project_local:
        warnings.append("custom-home-outside-project")
    choices = CHOICES if requires_user_choice else ()
    requires_initialization = not target.exists()
    if target.is_dir():
        marker = target / PROJECT_HOME_MANIFEST
        if marker.is_file():
            requires_initialization = False
        elif not any(target.iterdir()):
            requires_initialization = True
        elif source not in {"explicit", "environment"}:
            requires_initialization = True
    return ProjectHomeResolution(
        project_root=project_root,
        path=target,
        source=source,
        status=status,
        target_kind="project-local" if project_local else "custom",
        requires_user_choice=requires_user_choice,
        requires_initialization=requires_initialization,
        git_check_required=project_local,
        choices=choices,
        warnings=tuple(warnings),
    )


def resolve_project_home(
    project_root: Path,
    *,
    explicit_data_root: Path | None = None,
    remembered_home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProjectHomeResolution:
    """Resolve or propose one project home without creating filesystem state."""

    project = _absolute_path(project_root, "project root", must_exist=True)
    environment = os.environ if environ is None else environ
    if explicit_data_root is not None:
        return _resolution(
            project,
            explicit_data_root,
            source="explicit",
            requires_user_choice=False,
        )
    configured = environment.get(KRCN_HOME_ENV)
    if configured:
        return _resolution(
            project,
            Path(configured),
            source="environment",
            requires_user_choice=False,
        )
    if remembered_home is not None:
        return _resolution(
            project,
            remembered_home,
            source="remembered",
            requires_user_choice=False,
        )
    return _resolution(
        project,
        project / PROJECT_HOME_DIRECTORY,
        source="project-default",
        requires_user_choice=True,
    )


def select_project_home_parent(
    project_root: Path,
    selected_parent: Path,
) -> ProjectHomeResolution:
    """Resolve one approved alternate parent without creating its .krcn child."""

    project = _absolute_path(project_root, "project root", must_exist=True)
    parent = _absolute_path(selected_parent, "selected parent", must_exist=True)
    return _resolution(
        project,
        parent / PROJECT_HOME_DIRECTORY,
        source="user-selected",
        requires_user_choice=False,
    )


def choose_project_home(
    proposal: ProjectHomeResolution,
    choice: str,
    *,
    selected_parent: Path | None = None,
) -> ProjectHomeResolution | None:
    """Apply one user choice to a non-mutating project-home proposal."""

    if not proposal.requires_user_choice or proposal.source != "project-default":
        raise ProjectHomeError("project-home resolution is not awaiting a choice")
    if choice == "cancel":
        if selected_parent is not None:
            raise ProjectHomeError("cancel may not include a selected parent")
        return None
    if choice == "use-default":
        if selected_parent is not None:
            raise ProjectHomeError("default choice may not include a selected parent")
        return _resolution(
            proposal.project_root,
            proposal.path,
            source="project-default",
            requires_user_choice=False,
        )
    if choice == "choose-parent":
        if selected_parent is None:
            raise ProjectHomeError("alternate choice requires a selected parent")
        return select_project_home_parent(proposal.project_root, selected_parent)
    raise ProjectHomeError("project-home choice is invalid")

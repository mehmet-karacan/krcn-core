"""Resolve one portable KRCN user home independently from the core clone."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


KRCN_HOME_ENV = "KRCN_HOME"
LAYOUT_VERSION = 1


class UserHomeError(ValueError):
    """Raised when a KRCN user-home location is unsafe or ambiguous."""


@dataclass(frozen=True)
class UserHomeResolution:
    path: Path
    source: str
    layout_version: int = LAYOUT_VERSION

    def public_summary(self) -> dict[str, object]:
        """Describe the resolution without disclosing a machine-specific path."""

        return {
            "schema_version": 1,
            "layout_version": self.layout_version,
            "source": self.source,
            "path_disclosed": False,
        }


def _absolute_directory(value: Path, label: str) -> Path:
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise UserHomeError(f"{label} must be an absolute path")
    resolved = expanded.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise UserHomeError(f"{label} may not be a filesystem root")
    if resolved.exists() and resolved.is_symlink():
        raise UserHomeError(f"{label} may not be a symbolic link")
    if resolved.exists() and not resolved.is_dir():
        raise UserHomeError(f"{label} must be a directory")
    return resolved


def resolve_user_home(
    explicit: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home_directory: Path | None = None,
) -> UserHomeResolution:
    """Resolve the portable data root without depending on the core repository."""

    environment = os.environ if environ is None else environ
    platform_id = sys.platform if platform_name is None else platform_name

    if explicit is not None:
        return UserHomeResolution(
            _absolute_directory(explicit, "explicit KRCN user home"),
            "explicit",
        )

    configured = environment.get(KRCN_HOME_ENV)
    if configured:
        return UserHomeResolution(
            _absolute_directory(Path(configured), KRCN_HOME_ENV),
            "environment",
        )

    home = home_directory if home_directory is not None else Path.home()
    home = _absolute_directory(home, "operating-system home")
    if platform_id == "win32":
        local_app_data = environment.get("LOCALAPPDATA")
        candidate = (
            Path(local_app_data) / "KRCN"
            if local_app_data
            else home / "AppData" / "Local" / "KRCN"
        )
        source = "windows-default"
    elif platform_id == "darwin":
        candidate = home / "Library" / "Application Support" / "KRCN"
        source = "macos-default"
    else:
        xdg_data_home = environment.get("XDG_DATA_HOME")
        candidate = (
            Path(xdg_data_home) / "krcn"
            if xdg_data_home
            else home / ".local" / "share" / "krcn"
        )
        source = "xdg-default"
    return UserHomeResolution(_absolute_directory(candidate, source), source)


"""Install the KRCN CLI for the current Windows user without network access."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import winreg
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_ENVIRONMENT_KEY = r"Environment"
KRCN_CORE_HOME_ENV = "KRCN_CORE_HOME"
KRCN_HOME_ENV = "KRCN_HOME"


class CliInstallationError(RuntimeError):
    """Raised when the local CLI bootstrap cannot be completed safely."""


@dataclass(frozen=True)
class RegistryValue:
    exists: bool
    value: str | None
    value_type: int


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise CliInstallationError(
            f"Command failed with exit code {result.returncode}: {command[0]}"
        )


def _validate_repository() -> None:
    manifest_path = REPO_ROOT / ".ai" / "repository-context.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliInstallationError(
            "KRCN Core repository context could not be read."
        ) from exc
    if manifest.get("project", {}).get("id") != "krcn-core":
        raise CliInstallationError("This directory is not a KRCN Core repository.")


def _read_user_environment(name: str) -> RegistryValue:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        USER_ENVIRONMENT_KEY,
        access=winreg.KEY_READ,
    ) as key:
        try:
            value, value_type = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return RegistryValue(False, None, winreg.REG_SZ)
    return RegistryValue(True, str(value), value_type)


def _write_user_environment(name: str, value: str, value_type: int) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        USER_ENVIRONMENT_KEY,
        access=winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, name, 0, value_type, value)


def _restore_user_environment(name: str, previous: RegistryValue) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        USER_ENVIRONMENT_KEY,
        access=winreg.KEY_SET_VALUE,
    ) as key:
        if previous.exists and previous.value is not None:
            winreg.SetValueEx(key, name, 0, previous.value_type, previous.value)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def _append_path_entry(current: str | None, entry: Path) -> str:
    entries = [part for part in (current or "").split(";") if part]
    normalized = str(entry).rstrip("\\").casefold()
    if all(part.rstrip("\\").casefold() != normalized for part in entries):
        entries.append(str(entry))
    return ";".join(entries)


def _broadcast_environment_change() -> None:
    hwnd_broadcast = 0xFFFF
    wm_settingchange = 0x001A
    send_timeout_abort_if_hung = 0x0002
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        hwnd_broadcast,
        wm_settingchange,
        0,
        "Environment",
        send_timeout_abort_if_hung,
        5000,
        ctypes.byref(result),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install the KRCN CLI for the current Windows user."
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Show resolved effects without installing or changing user settings.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if os.name != "nt":
        raise CliInstallationError("This bootstrap currently supports Windows only.")
    if sys.version_info < (3, 11):
        raise CliInstallationError("Python 3.11 or newer is required.")

    _validate_repository()
    scripts_directory = Path(sysconfig.get_path("scripts")).resolve()
    executable = scripts_directory / "krcn.exe"

    print(f"KRCN Core repository: {REPO_ROOT}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"CLI scripts directory: {scripts_directory}")
    print(f"{KRCN_CORE_HOME_ENV} will be set for the current user.")
    print(f"{KRCN_HOME_ENV} will not be changed.")
    if args.plan_only:
        print("Plan completed. No change was applied.")
        return 0

    environment = os.environ.copy()
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    _run(
        [sys.executable, str(REPO_ROOT / "tools" / "verify_wheel.py")],
        cwd=REPO_ROOT,
        environment=environment,
    )
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--force-reinstall",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        environment=environment,
    )

    previous_core_home = _read_user_environment(KRCN_CORE_HOME_ENV)
    previous_path = _read_user_environment("Path")
    updated_path = _append_path_entry(previous_path.value, scripts_directory)
    try:
        _write_user_environment(
            KRCN_CORE_HOME_ENV,
            str(REPO_ROOT),
            winreg.REG_SZ,
        )
        _write_user_environment(
            "Path",
            updated_path,
            previous_path.value_type if previous_path.exists else winreg.REG_EXPAND_SZ,
        )
        _broadcast_environment_change()

        smoke_environment = os.environ.copy()
        smoke_environment[KRCN_CORE_HOME_ENV] = str(REPO_ROOT)
        smoke_environment["PATH"] = f"{scripts_directory};{smoke_environment['PATH']}"
        with tempfile.TemporaryDirectory() as directory:
            _run(
                [str(executable), "context", "--validate-only"],
                cwd=Path(directory),
                environment=smoke_environment,
            )
    except Exception:
        _restore_user_environment(KRCN_CORE_HOME_ENV, previous_core_home)
        _restore_user_environment("Path", previous_path)
        _broadcast_environment_change()
        raise

    print("KRCN CLI installation completed.")
    print("Open a new terminal and run: krcn doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

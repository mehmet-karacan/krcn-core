"""Install the KRCN CLI for the current user without network access."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shlex
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    import winreg
else:  # pragma: no cover - the Windows registry is platform specific
    winreg = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_ENVIRONMENT_KEY = r"Environment"
KRCN_CORE_HOME_ENV = "KRCN_CORE_HOME"
KRCN_HOME_ENV = "KRCN_HOME"
POSIX_BEGIN_MARKER = "# KRCN-CORE:BEGIN"
POSIX_END_MARKER = "# KRCN-CORE:END"


class CliInstallationError(RuntimeError):
    """Raised when the local CLI bootstrap cannot be completed safely."""


@dataclass(frozen=True)
class RegistryValue:
    exists: bool
    value: str | None
    value_type: int


@dataclass(frozen=True)
class PosixInstallation:
    environment_root: Path
    scripts_directory: Path
    executable: Path
    shell_profile: Path


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
    if winreg is None:
        raise CliInstallationError("Windows registry is unavailable on this platform.")
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
    if winreg is None:
        raise CliInstallationError("Windows registry is unavailable on this platform.")
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        USER_ENVIRONMENT_KEY,
        access=winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, name, 0, value_type, value)


def _restore_user_environment(name: str, previous: RegistryValue) -> None:
    if winreg is None:
        raise CliInstallationError("Windows registry is unavailable on this platform.")
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
    if os.name != "nt":
        return
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
        description="Install the KRCN CLI for the current user."
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Show resolved effects without installing or changing user settings.",
    )
    return parser


def _posix_installation(home: Path | None = None) -> PosixInstallation:
    user_home = (home or Path.home()).resolve()
    environment_root = user_home / ".local" / "share" / "krcn" / "cli"
    scripts_directory = environment_root / "bin"
    shell = Path(os.environ.get("SHELL", "")).name
    shell_profile = (
        user_home / ".zprofile"
        if sys.platform == "darwin" or shell == "zsh"
        else user_home / ".profile"
    )
    return PosixInstallation(
        environment_root=environment_root,
        scripts_directory=scripts_directory,
        executable=scripts_directory / "krcn",
        shell_profile=shell_profile,
    )


def _render_posix_profile(
    original: bytes,
    *,
    core_home: Path,
    scripts_directory: Path,
) -> bytes:
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliInstallationError("The shell profile must be UTF-8.") from exc
    begin_count = text.count(POSIX_BEGIN_MARKER)
    end_count = text.count(POSIX_END_MARKER)
    if (begin_count, end_count) not in {(0, 0), (1, 1)}:
        raise CliInstallationError("The shell profile KRCN markers are malformed.")
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline.join(
        (
            POSIX_BEGIN_MARKER,
            f"export {KRCN_CORE_HOME_ENV}={shlex.quote(str(core_home))}",
            f"export PATH={shlex.quote(str(scripts_directory))}:\"$PATH\"",
            POSIX_END_MARKER,
        )
    )
    if begin_count == 1:
        begin = text.index(POSIX_BEGIN_MARKER)
        end = text.index(POSIX_END_MARKER, begin) + len(POSIX_END_MARKER)
        rendered = text[:begin] + block + text[end:]
    elif text:
        separator = newline if text.endswith(newline) else newline * 2
        rendered = text + separator + block + newline
    else:
        rendered = block + newline
    return rendered.encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = path.stat().st_mode if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if previous_mode is not None:
            os.chmod(temporary_path, previous_mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _install_package(
    python_executable: Path,
    *,
    environment: dict[str, str],
) -> None:
    _run(
        [
            str(python_executable),
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


def _smoke_test(
    executable: Path,
    *,
    scripts_directory: Path,
    environment: dict[str, str],
) -> None:
    smoke_environment = environment.copy()
    smoke_environment[KRCN_CORE_HOME_ENV] = str(REPO_ROOT)
    smoke_environment["PATH"] = (
        f"{scripts_directory}{os.pathsep}{smoke_environment.get('PATH', '')}"
    )
    with tempfile.TemporaryDirectory() as directory:
        _run(
            [str(executable), "context", "--validate-only"],
            cwd=Path(directory),
            environment=smoke_environment,
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if sys.version_info < (3, 11):
        raise CliInstallationError("Python 3.11 or newer is required.")

    _validate_repository()
    posix = _posix_installation() if os.name != "nt" else None
    if posix is None:
        scripts_directory = Path(sysconfig.get_path("scripts")).resolve()
        executable = scripts_directory / "krcn.exe"
        shell_profile = None
    else:
        scripts_directory = posix.scripts_directory
        executable = posix.executable
        shell_profile = posix.shell_profile

    print(f"KRCN Core repository: {REPO_ROOT}")
    print(f"Platform: {sys.platform}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"CLI scripts directory: {scripts_directory}")
    if shell_profile is None:
        print(f"{KRCN_CORE_HOME_ENV} will be set for the current user.")
    else:
        print("A managed KRCN block will be added to the user shell profile.")
    print(f"{KRCN_HOME_ENV} will not be changed.")
    if args.plan_only:
        print("Plan completed. No change was applied.")
        return 0

    profile_existed = False
    original_profile = b""
    rendered_profile = b""
    if posix is not None:
        if posix.shell_profile.is_symlink():
            raise CliInstallationError("The shell profile may not be a symbolic link.")
        if posix.shell_profile.exists() and not posix.shell_profile.is_file():
            raise CliInstallationError("The shell profile must be a regular file.")
        profile_existed = posix.shell_profile.exists()
        original_profile = (
            posix.shell_profile.read_bytes() if profile_existed else b""
        )
        rendered_profile = _render_posix_profile(
            original_profile,
            core_home=REPO_ROOT,
            scripts_directory=scripts_directory,
        )

    environment = os.environ.copy()
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    _run(
        [sys.executable, str(REPO_ROOT / "tools" / "verify_wheel.py")],
        cwd=REPO_ROOT,
        environment=environment,
    )
    if posix is None:
        install_python = Path(sys.executable)
    else:
        _run(
            [sys.executable, "-m", "venv", str(posix.environment_root)],
            cwd=REPO_ROOT,
            environment=environment,
        )
        install_python = posix.environment_root / "bin" / "python"
    _install_package(install_python, environment=environment)

    if posix is None:
        assert winreg is not None
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
                previous_path.value_type
                if previous_path.exists
                else winreg.REG_EXPAND_SZ,
            )
            _broadcast_environment_change()
            _smoke_test(
                executable,
                scripts_directory=scripts_directory,
                environment=environment,
            )
        except Exception:
            _restore_user_environment(KRCN_CORE_HOME_ENV, previous_core_home)
            _restore_user_environment("Path", previous_path)
            _broadcast_environment_change()
            raise
    else:
        try:
            _atomic_write(posix.shell_profile, rendered_profile)
            _smoke_test(
                executable,
                scripts_directory=scripts_directory,
                environment=environment,
            )
        except Exception:
            if profile_existed:
                _atomic_write(posix.shell_profile, original_profile)
            else:
                posix.shell_profile.unlink(missing_ok=True)
            raise

    print("KRCN CLI installation completed.")
    print("Open a new terminal and run: krcn doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

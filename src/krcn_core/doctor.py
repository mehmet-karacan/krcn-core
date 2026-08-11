"""Repository health checks for the Phase 1 KRCN Core baseline."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .cli.registry import compatibility_registry
from .foundation import load_json, validate_foundation, verify_repository
from .provider_gate import load_provider_gate_policy, select_default_provider
from .repository_context import validate_repository_context


@dataclass(frozen=True)
class DoctorCheck:
    check_id: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.check_id,
            "passed": self.passed,
            "detail": self.detail,
        }


def _check(check_id: str, errors: list[object], success: str) -> DoctorCheck:
    return DoctorCheck(
        check_id=check_id,
        passed=not errors,
        detail=success if not errors else f"{len(errors)} finding(s)",
    )


def _tracked_local_data(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--", ".krcn"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return ["git inspection failed"]
    return [line for line in result.stdout.splitlines() if line.strip()]


def run_doctor(repo_root: Path) -> tuple[DoctorCheck, ...]:
    """Run offline and non-mutating repository health checks."""

    repo_root = repo_root.resolve()
    checks = [
        _check(
            "repository-context",
            validate_repository_context(repo_root),
            "shared context is valid",
        ),
        _check(
            "foundation-contracts",
            validate_foundation(repo_root),
            "ownership and import contracts are valid",
        ),
        _check(
            "repository-content",
            verify_repository(repo_root),
            "tracked and candidate content is clean",
        ),
    ]
    commands = compatibility_registry().all()
    checks.append(
        DoctorCheck(
            "cli-catalog",
            len(commands) == 29 and len({item.command_id for item in commands}) == 29,
            "29 reviewed commands are registered",
        )
    )
    try:
        policy = load_provider_gate_policy(repo_root)
        default_provider = select_default_provider(policy)
        provider_errors = [] if default_provider == "deterministic-hashing" else [default_provider]
    except ValueError as exc:
        provider_errors = [str(exc)]
    checks.append(
        _check(
            "offline-provider",
            provider_errors,
            "offline deterministic provider is the default",
        )
    )
    checks.append(
        _check(
            "tracked-local-data",
            _tracked_local_data(repo_root),
            "no local user data is tracked",
        )
    )
    current_work = load_json(repo_root / ".ai" / "current-work.json")
    cli_baseline = load_json(repo_root / ".ai" / "cli-baseline.json")
    phase_errors = []
    if current_work.get("phase_id") != "phase-1" or current_work.get("status") != "completed":
        phase_errors.append("phase state")
    if cli_baseline.get("status") != "ready":
        phase_errors.append("CLI baseline state")
    checks.append(
        _check(
            "phase-one-baseline",
            phase_errors,
            "Phase 1 baseline is complete and ready",
        )
    )
    return tuple(checks)

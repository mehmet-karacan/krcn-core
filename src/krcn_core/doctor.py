"""Offline repository health checks for completed KRCN Core baselines."""

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
    cli_baseline = load_json(repo_root / ".ai" / "cli-baseline.json")
    phase_errors = []
    if cli_baseline.get("status") != "ready":
        phase_errors.append("CLI baseline state")
    if not (repo_root / "docs" / "progress" / "PHASE-1-COMPLETION.md").is_file():
        phase_errors.append("Phase 1 completion evidence")
    checks.append(
        _check(
            "phase-one-baseline",
            phase_errors,
            "Phase 1 baseline is complete and ready",
        )
    )
    phase_two = load_json(repo_root / ".ai" / "phase-2-baseline.json")
    phase_two_errors = []
    if phase_two.get("status") != "ready":
        phase_two_errors.append("Phase 2 baseline state")
    if phase_two.get("completed_steps") != 10:
        phase_two_errors.append("Phase 2 completed steps")
    if not (repo_root / "docs" / "progress" / "PHASE-2-COMPLETION.md").is_file():
        phase_two_errors.append("Phase 2 completion evidence")
    checks.append(
        _check(
            "phase-two-baseline",
            phase_two_errors,
            "Phase 2 local workspace baseline is complete and ready",
        )
    )
    phase_three = load_json(repo_root / ".ai" / "phase-3-baseline.json")
    phase_three_errors = []
    if phase_three.get("status") != "ready":
        phase_three_errors.append("Phase 3 baseline state")
    if phase_three.get("completed_steps") != 10:
        phase_three_errors.append("Phase 3 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-3-COMPLETION.md"
    ).is_file():
        phase_three_errors.append("Phase 3 completion evidence")
    checks.append(
        _check(
            "phase-three-baseline",
            phase_three_errors,
            "Phase 3 safe merge baseline is complete and ready",
        )
    )
    phase_four = load_json(repo_root / ".ai" / "phase-4-baseline.json")
    phase_four_errors = []
    if phase_four.get("status") != "ready":
        phase_four_errors.append("Phase 4 baseline state")
    if phase_four.get("completed_steps") != 10:
        phase_four_errors.append("Phase 4 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-4-COMPLETION.md"
    ).is_file():
        phase_four_errors.append("Phase 4 completion evidence")
    checks.append(
        _check(
            "phase-four-baseline",
            phase_four_errors,
            "Phase 4 context, knowledge, and memory baseline is complete and ready",
        )
    )
    phase_five = load_json(repo_root / ".ai" / "phase-5-baseline.json")
    phase_five_errors = []
    if phase_five.get("status") != "ready":
        phase_five_errors.append("Phase 5 baseline state")
    if phase_five.get("completed_steps") != 10:
        phase_five_errors.append("Phase 5 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-5-COMPLETION.md"
    ).is_file():
        phase_five_errors.append("Phase 5 completion evidence")
    checks.append(
        _check(
            "phase-five-baseline",
            phase_five_errors,
            "Phase 5 orchestrator baseline is complete and ready",
        )
    )
    return tuple(checks)

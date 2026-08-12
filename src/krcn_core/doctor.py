"""Offline repository health checks for completed KRCN Core baselines."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .cli.registry import compatibility_registry
from .foundation import load_json, validate_foundation, verify_repository
from .provider_gate import load_provider_gate_policy, select_default_provider
from .repository_context import validate_repository_context
from .release_quality import validate_release_quality_repository


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


def _sqlite_features() -> list[str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE sample_fts USING fts5(content)")
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            return ["SQLite query_only is unavailable"]
    except sqlite3.Error as exc:
        return [f"SQLite runtime feature is unavailable: {exc}"]
    finally:
        connection.close()
    return []


def _coverage_baseline(repo_root: Path) -> list[str]:
    try:
        baseline = load_json(repo_root / ".ai" / "coverage-baseline.json")
    except ValueError as exc:
        return [str(exc)]
    errors = []
    if baseline.get("method") != "python-monitoring-line-events":
        errors.append("coverage method")
    measured = baseline.get("line_coverage_percent")
    minimum = baseline.get("minimum_line_coverage_percent")
    if (
        not isinstance(measured, (int, float))
        or not isinstance(minimum, (int, float))
        or measured < minimum
    ):
        errors.append("coverage threshold")
    if not (repo_root / "tools" / "measure_coverage.py").is_file():
        errors.append("coverage tool")
    return errors


def _runtime_home(data_root: Path) -> list[str]:
    root = data_root.resolve()
    if not root.is_dir() or root.is_symlink():
        return ["runtime home is unavailable or unsafe"]
    errors = []
    for name in ("secrets", "derived", "runtime", "locks"):
        candidate = root / name
        if candidate.is_symlink():
            errors.append(f"runtime home {name} path is a symbolic link")
    index = root / "derived" / "retrieval" / "hybrid-v1.sqlite"
    if index.exists():
        if index.is_symlink() or not index.is_file():
            errors.append("hybrid index path is unsafe")
        else:
            connection = sqlite3.connect(index)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                metadata = dict(
                    connection.execute("SELECT key, value FROM metadata").fetchall()
                )
                if integrity != "ok" or metadata.get("index_revision") != "1":
                    errors.append("hybrid index integrity or revision")
            except sqlite3.Error:
                errors.append("hybrid index cannot be inspected")
            finally:
                connection.close()
    return errors


def run_doctor(
    repo_root: Path,
    data_root: Path | None = None,
) -> tuple[DoctorCheck, ...]:
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
    checks.append(
        _check(
            "release-quality",
            validate_release_quality_repository(repo_root),
            "cross-platform release and portability quality gates are valid",
        )
    )
    checks.append(
        _check(
            "sqlite-runtime",
            _sqlite_features(),
            "SQLite read-only and FTS5 features are available",
        )
    )
    checks.append(
        _check(
            "coverage-baseline",
            _coverage_baseline(repo_root),
            "versioned line coverage remains above its baseline threshold",
        )
    )
    if data_root is not None:
        checks.append(
            _check(
                "runtime-home",
                _runtime_home(data_root),
                "local runtime home and derived index are healthy",
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
    phase_six = load_json(repo_root / ".ai" / "phase-6-baseline.json")
    phase_six_errors = []
    if phase_six.get("status") != "ready":
        phase_six_errors.append("Phase 6 baseline state")
    if phase_six.get("completed_steps") != 10:
        phase_six_errors.append("Phase 6 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-6-COMPLETION.md"
    ).is_file():
        phase_six_errors.append("Phase 6 completion evidence")
    checks.append(
        _check(
            "phase-six-baseline",
            phase_six_errors,
            "Phase 6 release, quality, and portability baseline is complete and ready",
        )
    )
    phase_seven = load_json(repo_root / ".ai" / "phase-7-baseline.json")
    phase_seven_errors = []
    if phase_seven.get("status") != "ready":
        phase_seven_errors.append("Phase 7 baseline state")
    if phase_seven.get("completed_steps") != 7:
        phase_seven_errors.append("Phase 7 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-7-COMPLETION.md"
    ).is_file():
        phase_seven_errors.append("Phase 7 completion evidence")
    checks.append(
        _check(
            "phase-seven-baseline",
            phase_seven_errors,
            "Phase 7 natural-language project learning baseline is complete and ready",
        )
    )
    return tuple(checks)

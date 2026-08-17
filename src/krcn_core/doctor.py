"""Offline repository health checks for completed KRCN Core baselines."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .architecture_contracts import validate_architecture_contracts_repository
from .baseline_attestation import resolve_baseline_attestations
from .cli.registry import compatibility_registry
from .foundation import load_json, validate_foundation, verify_repository
from .home_layout import home_layout_version
from .hybrid_retrieval import hybrid_index_path
from .effect_ledger_store import EffectLedgerStore, EffectLedgerStoreError
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


def _baseline_attestation(repo_root: Path) -> list[str]:
    _, errors = resolve_baseline_attestations(repo_root)
    return errors


def _runtime_home(data_root: Path) -> list[str]:
    root = data_root.resolve()
    if not root.is_dir() or root.is_symlink():
        return ["runtime home is unavailable or unsafe"]
    errors = []
    for name in ("secrets", "derived", "runtime", "locks", "projects", "global", "local"):
        candidate = root / name
        if candidate.is_symlink():
            errors.append(f"runtime home {name} path is a symbolic link")
    try:
        layout_version = home_layout_version(root)
    except ValueError:
        return ["runtime home layout marker is invalid"]
    index = hybrid_index_path(root)
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
    source_code_directories = [root / "derived" / "retrieval" / "source-code-v1"]
    if layout_version >= 2:
        source_code_directories.extend(
            path
            for path in sorted(
                (root / "projects").glob(
                    "*/derived/retrieval/source-code-v1.sqlite"
                )
            )
        )
    inspected_indexes = set()
    for source_code_directory in source_code_directories:
        if source_code_directory.is_file() and source_code_directory.name.endswith(".sqlite"):
            candidates = (source_code_directory,)
        elif source_code_directory.exists():
            if source_code_directory.is_symlink() or not source_code_directory.is_dir():
                errors.append("source code index directory is unsafe")
                continue
            candidates = tuple(source_code_directory.glob("*.sqlite"))
        else:
            candidates = ()
        for source_code_index in candidates:
            if source_code_index in inspected_indexes:
                continue
            inspected_indexes.add(source_code_index)
            if source_code_index.is_symlink() or not source_code_index.is_file():
                errors.append("source code index path is unsafe")
                continue
            connection = sqlite3.connect(source_code_index)
            try:
                integrity = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
                metadata = dict(
                    connection.execute(
                        "SELECT key, value FROM metadata"
                    ).fetchall()
                )
                chunk_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(chunks)"
                    ).fetchall()
                }
                if (
                    integrity != "ok"
                    or metadata.get("index_revision") != "1"
                    or metadata.get("source_content_persisted") != "false"
                    or metadata.get("remote_provider_used") != "false"
                    or {"content", "text"}.intersection(chunk_columns)
                ):
                    errors.append("source code index integrity or boundary")
            except sqlite3.Error:
                errors.append("source code index cannot be inspected")
            finally:
                connection.close()
    queue_indexes = tuple(
        root.glob("projects/*/runtime/queue/scheduler-v1.sqlite")
    )
    for queue_index in queue_indexes:
        if queue_index.is_symlink() or not queue_index.is_file():
            errors.append("runtime queue path is unsafe")
            continue
        connection = sqlite3.connect(queue_index)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            metadata = dict(
                connection.execute("SELECT key, value FROM metadata").fetchall()
            )
            lease_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(leases)"
                ).fetchall()
            }
            queue_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(queue_items)"
                ).fetchall()
            }
            migration_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='queue_schema_migrations'"
            ).fetchone()
            if (
                integrity != "ok"
                or metadata.get("schema_version") != "2"
                or "owner_digest" not in lease_columns
                or "owner_token" in lease_columns
                or not {
                    "ledger_required", "validation_gate_id",
                    "effect_claim_id", "effect_receipt_id",
                }.issubset(queue_columns)
                or migration_table is None
            ):
                errors.append("runtime queue integrity or secret boundary")
        except sqlite3.Error:
            errors.append("runtime queue cannot be inspected")
        finally:
            connection.close()
    for ledger_index in root.glob("projects/*/runtime/effects/effect-ledger.sqlite"):
        if ledger_index.is_symlink() or not ledger_index.is_file():
            errors.append("effect ledger path is unsafe")
            continue
        try:
            report = EffectLedgerStore(ledger_index).doctor_report()
            if not report["integrity_verified"]:
                errors.append("effect ledger contract or integrity")
                continue
            recovery = set(report["recovery_required_claim_ids"])
            if not recovery:
                continue
            queue_index = ledger_index.parent.parent / "queue" / "scheduler-v1.sqlite"
            active = set()
            if queue_index.is_file() and not queue_index.is_symlink():
                connection = sqlite3.connect(queue_index)
                try:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(queue_items)")}
                    if "effect_claim_id" in columns:
                        active = {
                            row[0] for row in connection.execute(
                                "SELECT q.effect_claim_id FROM queue_items q JOIN leases l ON l.queue_id=q.queue_id WHERE q.effect_claim_id IS NOT NULL AND q.status='leased'"
                            )
                        }
                finally:
                    connection.close()
            if recovery - active:
                errors.append("effect ledger has unattended recovery-required claims")
        except (EffectLedgerStoreError, sqlite3.Error, ValueError):
            errors.append("effect ledger cannot be inspected")
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
    checks.append(
        _check(
            "baseline-attestation",
            _baseline_attestation(repo_root),
            "quality baselines name the commit they were measured on",
        )
    )
    checks.append(
        _check(
            "v1-architecture-contracts",
            validate_architecture_contracts_repository(repo_root),
            "frozen V1 architecture contracts still resolve to real evidence",
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
    phase_eight = load_json(repo_root / ".ai" / "phase-8-baseline.json")
    phase_eight_errors = []
    if phase_eight.get("status") != "ready":
        phase_eight_errors.append("Phase 8 baseline state")
    if phase_eight.get("completed_steps") != 10:
        phase_eight_errors.append("Phase 8 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-8-COMPLETION.md"
    ).is_file():
        phase_eight_errors.append("Phase 8 completion evidence")
    checks.append(
        _check(
            "phase-eight-baseline",
            phase_eight_errors,
            "Phase 8 project-home and production-hardening baseline is complete",
        )
    )
    phase_nine = load_json(repo_root / ".ai" / "phase-9-baseline.json")
    phase_nine_errors = []
    if phase_nine.get("status") != "ready":
        phase_nine_errors.append("Phase 9 baseline state")
    if phase_nine.get("completed_steps") != 8:
        phase_nine_errors.append("Phase 9 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-9-COMPLETION.md"
    ).is_file():
        phase_nine_errors.append("Phase 9 completion evidence")
    checks.append(
        _check(
            "phase-nine-baseline",
            phase_nine_errors,
            "Phase 9 continuous project integration baseline is complete",
        )
    )
    phase_ten = load_json(repo_root / ".ai" / "phase-10-baseline.json")
    phase_ten_errors = []
    if phase_ten.get("status") != "ready":
        phase_ten_errors.append("Phase 10 baseline state")
    if phase_ten.get("completed_steps") != 10:
        phase_ten_errors.append("Phase 10 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-10-COMPLETION.md"
    ).is_file():
        phase_ten_errors.append("Phase 10 completion evidence")
    checks.append(
        _check(
            "phase-ten-baseline",
            phase_ten_errors,
            "Phase 10 source-code RAG index baseline is complete",
        )
    )
    phase_eleven = load_json(repo_root / ".ai" / "phase-11-baseline.json")
    phase_eleven_errors = []
    if phase_eleven.get("status") != "ready":
        phase_eleven_errors.append("Phase 11 baseline state")
    if phase_eleven.get("completed_steps") != 9:
        phase_eleven_errors.append("Phase 11 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-11-COMPLETION.md"
    ).is_file():
        phase_eleven_errors.append("Phase 11 completion evidence")
    checks.append(
        _check(
            "phase-eleven-baseline",
            phase_eleven_errors,
            "Phase 11 project-capsule layout v2 baseline is complete",
        )
    )
    phase_twelve = load_json(repo_root / ".ai" / "phase-12-baseline.json")
    phase_twelve_errors = []
    if phase_twelve.get("status") != "ready":
        phase_twelve_errors.append("Phase 12 baseline state")
    if phase_twelve.get("completed_steps") != 7:
        phase_twelve_errors.append("Phase 12 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-12-COMPLETION.md"
    ).is_file():
        phase_twelve_errors.append("Phase 12 completion evidence")
    checks.append(
        _check(
            "phase-twelve-baseline",
            phase_twelve_errors,
            "Phase 12 authoritative Work Graph baseline is complete",
        )
    )
    phase_thirteen = load_json(repo_root / ".ai" / "phase-13-baseline.json")
    phase_thirteen_errors = []
    if phase_thirteen.get("status") != "ready":
        phase_thirteen_errors.append("Phase 13 baseline state")
    if phase_thirteen.get("completed_steps") != 10:
        phase_thirteen_errors.append("Phase 13 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-13-COMPLETION.md"
    ).is_file():
        phase_thirteen_errors.append("Phase 13 completion evidence")
    checks.append(
        _check(
            "phase-thirteen-baseline",
            phase_thirteen_errors,
            "Phase 13 agent runtime queue baseline is complete",
        )
    )
    phase_fourteen = load_json(repo_root / ".ai" / "phase-14-baseline.json")
    phase_fourteen_errors = []
    if phase_fourteen.get("status") != "ready":
        phase_fourteen_errors.append("Phase 14 baseline state")
    if phase_fourteen.get("completed_steps") != 9:
        phase_fourteen_errors.append("Phase 14 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-14-COMPLETION.md"
    ).is_file():
        phase_fourteen_errors.append("Phase 14 completion evidence")
    checks.append(
        _check(
            "phase-fourteen-baseline",
            phase_fourteen_errors,
            "Phase 14 Oracle metadata RAG baseline is complete",
        )
    )
    phase_fifteen = load_json(repo_root / ".ai" / "phase-15-baseline.json")
    phase_fifteen_errors = []
    if phase_fifteen.get("status") != "ready":
        phase_fifteen_errors.append("Phase 15 baseline state")
    if phase_fifteen.get("completed_steps") != 8:
        phase_fifteen_errors.append("Phase 15 completed steps")
    if not (
        repo_root / "docs" / "progress" / "PHASE-15-COMPLETION.md"
    ).is_file():
        phase_fifteen_errors.append("Phase 15 completion evidence")
    checks.append(
        _check(
            "phase-fifteen-baseline",
            phase_fifteen_errors,
            "Phase 15 unified retrieval baseline is complete",
        )
    )
    return tuple(checks)

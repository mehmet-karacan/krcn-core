"""Versioned Phase 6 release, package, platform, and rollback quality gates."""

from __future__ import annotations

from pathlib import Path

from .application import OPERATIONS
from .foundation import load_json


REQUIRED_PLATFORMS = {"linux", "windows", "macos"}
REQUIRED_PORTABILITY_OPERATIONS = {
    "project.rebind",
    "portability.backup",
    "portability.restore",
    "portability.migrate-repo-local",
    "portability.merge-project-home",
}
REQUIRED_PACKAGE_MODULES = {
    "krcn_core/user_home.py",
    "krcn_core/source_rebind.py",
    "krcn_core/portable_backup.py",
    "krcn_core/portable_restore.py",
    "krcn_core/repo_local_migration.py",
    "krcn_core/project_home_merge.py",
}


def validate_release_quality(payload: object) -> list[str]:
    """Validate the complete release quality profile without external services."""

    if not isinstance(payload, dict):
        return ["release quality profile must be an object"]
    errors: list[str] = []
    if payload.get("schema_ref") != "schemas/release-quality.schema.json":
        errors.append("release quality schema reference is invalid")
    if payload.get("schema_version") != 1:
        errors.append("release quality schema version is invalid")
    platforms = payload.get("supported_platforms")
    if not isinstance(platforms, list) or set(platforms) != REQUIRED_PLATFORMS:
        errors.append("release quality platforms must include Linux, Windows, and macOS")
    if payload.get("user_home_layout_version") != 1:
        errors.append("release quality user-home layout version is invalid")
    operations = payload.get("required_operations")
    if not isinstance(operations, list) or set(operations) != REQUIRED_PORTABILITY_OPERATIONS:
        errors.append("release quality portability operations are incomplete")
    elif not set(operations).issubset(OPERATIONS):
        errors.append("release quality operation is unavailable")
    modules = payload.get("required_package_modules")
    if not isinstance(modules, list) or set(modules) != REQUIRED_PACKAGE_MODULES:
        errors.append("release quality package modules are incomplete")
    gates = payload.get("required_gates")
    expected_gates = {
        "repository-verify",
        "full-tests",
        "coverage-baseline",
        "doctor",
        "offline-wheel-install",
        "portable-backup-restore",
        "external-source-no-copy",
        "user-policy-preserved",
        "rollback-ready",
    }
    if not isinstance(gates, list) or set(gates) != expected_gates:
        errors.append("release quality gates are incomplete")
    rollback = payload.get("rollback_guarantees")
    if not isinstance(rollback, dict) or rollback != {
        "core_deployment": "automatic-on-verification-failure",
        "portable_restore": "target-not-published-before-verification",
        "repo_local_migration": "source-preserved",
    }:
        errors.append("release quality rollback guarantees are invalid")
    return errors


def validate_release_quality_repository(repo_root: Path) -> list[str]:
    """Check profile, package sources, CI workflow, and required specifications."""

    root = repo_root.resolve()
    try:
        profile = load_json(root / "config" / "release-quality.json")
    except ValueError as exc:
        return [str(exc)]
    errors = validate_release_quality(profile)
    for module in REQUIRED_PACKAGE_MODULES:
        source = root / "src" / module
        if not source.is_file():
            errors.append(f"required package module is missing: {module}")
    workflow = root / ".github" / "workflows" / "quality.yml"
    if not workflow.is_file():
        errors.append("cross-platform quality workflow is missing")
    specification = root / "docs" / "specifications" / "RELEASE-QUALITY-GATES.md"
    if not specification.is_file():
        errors.append("release quality specification is missing")
    return errors

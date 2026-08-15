"""Bind versioned quality baselines to the source commit they were measured on.

A baseline record that does not name its measurement commit cannot prove that
the recorded test count or coverage still describes the current tree. This
module keeps that binding explicit and machine-checkable without contacting any
remote service.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .foundation import load_json


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
COVERAGE_BASELINE_REF = ".ai/coverage-baseline.json"
CLI_BASELINE_REF = ".ai/cli-baseline.json"
ATTESTED_BASELINES = (COVERAGE_BASELINE_REF, CLI_BASELINE_REF)


@dataclass(frozen=True)
class BaselineAttestation:
    """Resolved attestation state for one versioned baseline record."""

    baseline_ref: str
    source_commit: str
    matches_requested_commit: bool | None

    def as_dict(self) -> dict:
        return {
            "baseline_ref": self.baseline_ref,
            "source_commit": self.source_commit,
            "matches_requested_commit": self.matches_requested_commit,
        }


def normalize_commit(value: object) -> str | None:
    """Return the lowercase commit identifier when it is a valid short or full SHA."""

    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if not COMMIT_PATTERN.fullmatch(candidate):
        return None
    return candidate


def commits_match(recorded: str, requested: str) -> bool:
    """Compare commits by shared prefix so short baselines stay comparable."""

    shared = min(len(recorded), len(requested))
    return recorded[:shared] == requested[:shared]


def validate_baseline_attestation(payload: object, baseline_ref: str) -> list[str]:
    """Check that a baseline record carries a usable measurement commit."""

    if not isinstance(payload, dict):
        return [f"{baseline_ref} must be an object"]
    if normalize_commit(payload.get("source_commit")) is None:
        return [f"{baseline_ref} source_commit is missing or invalid"]
    return []


def validate_coverage_threshold(payload: object) -> list[str]:
    """Check that the recorded coverage still meets the recorded minimum."""

    if not isinstance(payload, dict):
        return [f"{COVERAGE_BASELINE_REF} must be an object"]
    measured = payload.get("line_coverage_percent")
    minimum = payload.get("minimum_line_coverage_percent")
    if not isinstance(measured, (int, float)) or not isinstance(minimum, (int, float)):
        return [f"{COVERAGE_BASELINE_REF} coverage values are invalid"]
    if measured < minimum:
        return [f"{COVERAGE_BASELINE_REF} coverage is below the recorded minimum"]
    return []


def resolve_baseline_attestations(
    repo_root: Path,
    requested_commit: str | None = None,
) -> tuple[list[BaselineAttestation], list[str]]:
    """Resolve every attested baseline and report validation errors."""

    root = repo_root.resolve()
    normalized_request = normalize_commit(requested_commit) if requested_commit else None
    if requested_commit and normalized_request is None:
        return [], ["requested commit is not a valid object name"]

    attestations: list[BaselineAttestation] = []
    errors: list[str] = []
    for baseline_ref in ATTESTED_BASELINES:
        try:
            payload = load_json(root / Path(baseline_ref))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        record_errors = validate_baseline_attestation(payload, baseline_ref)
        if baseline_ref == COVERAGE_BASELINE_REF:
            record_errors.extend(validate_coverage_threshold(payload))
        if record_errors:
            errors.extend(record_errors)
            continue
        source_commit = normalize_commit(payload.get("source_commit"))
        assert source_commit is not None
        matches = (
            commits_match(source_commit, normalized_request)
            if normalized_request
            else None
        )
        attestations.append(
            BaselineAttestation(
                baseline_ref=baseline_ref,
                source_commit=source_commit,
                matches_requested_commit=matches,
            )
        )
    return attestations, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify that quality baselines name their measurement commit"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root",
    )
    parser.add_argument(
        "--commit",
        default=None,
        help="Commit the current verification run is measuring",
    )
    parser.add_argument(
        "--require-current",
        action="store_true",
        help="Fail when a baseline was measured on a different commit",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    return parser


def _render_text(
    attestations: Sequence[BaselineAttestation],
    stale: Sequence[BaselineAttestation],
) -> str:
    lines = ["Baseline attestation:"]
    for attestation in attestations:
        suffix = ""
        if attestation.matches_requested_commit is False:
            suffix = " (measured on an earlier commit)"
        elif attestation.matches_requested_commit is True:
            suffix = " (current)"
        lines.append(f"- {attestation.baseline_ref}: {attestation.source_commit}{suffix}")
    if stale:
        lines.append(
            "Stale baselines must be refreshed before a release is published."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    attestations, errors = resolve_baseline_attestations(args.repo, args.commit)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    stale = [item for item in attestations if item.matches_requested_commit is False]
    if args.format == "json":
        print(
            json.dumps(
                {
                    "requested_commit": normalize_commit(args.commit) if args.commit else None,
                    "baselines": [item.as_dict() for item in attestations],
                    "stale_baselines": [item.baseline_ref for item in stale],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_render_text(attestations, stale))

    if stale and args.require_current:
        for item in stale:
            print(
                f"ERROR: {item.baseline_ref} was measured on {item.source_commit}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

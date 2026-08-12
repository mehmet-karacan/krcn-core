#!/usr/bin/env python3
"""Measure dependency-free line coverage for the full unittest suite."""

from __future__ import annotations

import argparse
import dis
import json
import os
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (REPO_ROOT / "src" / "krcn_core").resolve()
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))


def _executable_lines(code: types.CodeType) -> set[int]:
    lines = {
        line
        for _, line in dis.findlinestarts(code)
        if isinstance(line, int) and line > 0
    }
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            lines.update(_executable_lines(value))
    return lines


def _source_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _planned_lines(path: Path) -> set[int]:
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    return _executable_lines(code)


def measure() -> tuple[dict[str, object], unittest.result.TestResult]:
    executed: dict[Path, set[int]] = {}
    code_paths: dict[types.CodeType, Path | None] = {}
    source_prefix = os.path.normcase(str(SOURCE_ROOT)) + os.sep
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is None:
        raise RuntimeError("coverage measurement requires Python 3.12 or newer")

    def line_callback(code, line_number):
        if code not in code_paths:
            candidate = os.path.normcase(os.path.abspath(code.co_filename))
            code_paths[code] = (
                Path(candidate) if candidate.startswith(source_prefix) else None
            )
        path = code_paths[code]
        if path is None:
            return
        executed.setdefault(path, set()).add(line_number)

    suite = unittest.defaultTestLoader.discover(str(REPO_ROOT / "tests"))
    tool_id = monitoring.COVERAGE_ID
    monitoring.use_tool_id(tool_id, "krcn-coverage")
    monitoring.register_callback(tool_id, monitoring.events.LINE, line_callback)
    monitoring.set_events(tool_id, monitoring.events.LINE)
    try:
        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)
    finally:
        monitoring.set_events(tool_id, 0)
        monitoring.register_callback(tool_id, monitoring.events.LINE, None)
        monitoring.free_tool_id(tool_id)
    files = []
    total_planned = 0
    total_executed = 0
    for path in _source_files():
        planned = _planned_lines(path)
        covered = planned & executed.get(path, set())
        total_planned += len(planned)
        total_executed += len(covered)
        files.append(
            {
                "path": path.relative_to(REPO_ROOT / "src").as_posix(),
                "executable_lines": len(planned),
                "covered_lines": len(covered),
                "percent": float(f"{(100 * len(covered) / len(planned) if planned else 100):.2f}"),
            }
        )
    percent = 100 * total_executed / total_planned if total_planned else 100
    return (
        {
            "schema_version": 1,
            "method": "python-monitoring-line-events",
            "scope": "src/krcn_core",
            "test_count": result.testsRun,
            "skipped_test_count": len(result.skipped),
            "executable_lines": total_planned,
            "covered_lines": total_executed,
            "line_coverage_percent": float(f"{percent:.2f}"),
            "files": files,
        },
        result,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimum", type=float, default=60.0)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.minimum <= 100:
        parser.error("minimum must be between 0 and 100")
    report, result = measure()
    if args.summary_only:
        report.pop("files")
    print(json.dumps(report, indent=2))
    if not result.wasSuccessful():
        return 1
    return 0 if float(report["line_coverage_percent"]) >= args.minimum else 1


if __name__ == "__main__":
    raise SystemExit(main())

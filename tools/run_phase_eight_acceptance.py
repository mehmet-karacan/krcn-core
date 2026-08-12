#!/usr/bin/env python3
"""Run the complete Phase 8 acceptance matrix."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

MODULES = (
    "test_phase_eight_kickoff",
    "test_project_home",
    "test_project_home_initialization",
    "test_project_home_client_integration",
    "test_project_home_portability",
    "test_deployment",
    "test_local_store",
    "test_phase_eight_runtime_integration",
    "test_hybrid_retrieval",
    "test_phase_eight_quality_ux",
    "test_phase_eight_completion",
)


def main() -> int:
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name) for name in MODULES
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

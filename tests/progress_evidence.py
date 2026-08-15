"""Shared helpers for locating durable progress evidence.

`.ai/current-work.json` is a bounded pointer to the active phase. Completed
phases keep their evidence in `docs/progress/PROGRESS-KATALOGU.md`, which is the
canonical index of every progress record. Phase tests therefore assert against
the catalog instead of the active pointer.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRESS_DIR = "docs/progress"
CATALOG_REF = f"{PROGRESS_DIR}/PROGRESS-KATALOGU.md"
_ENTRY_PATTERN = re.compile(r"^- `([A-Za-z0-9._-]+\.md)`$")


def catalogued_progress_refs(repo_root: Path | None = None) -> set[str]:
    """Return every repository-relative progress record listed in the catalog."""

    root = (repo_root or REPO_ROOT).resolve()
    catalog = (root / Path(CATALOG_REF)).read_text(encoding="utf-8")
    references = set()
    for line in catalog.splitlines():
        match = _ENTRY_PATTERN.match(line.strip())
        if match:
            references.add(f"{PROGRESS_DIR}/{match.group(1)}")
    return references


def assert_progress_evidence(test, *references: str, repo_root: Path | None = None) -> None:
    """Assert that each progress record exists and stays reachable from the catalog."""

    root = (repo_root or REPO_ROOT).resolve()
    catalogued = catalogued_progress_refs(root)
    for reference in references:
        test.assertTrue(
            (root / Path(reference)).is_file(),
            f"missing progress record: {reference}",
        )
        test.assertIn(reference, catalogued)

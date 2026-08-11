"""Run the KRCN Core repository context resolver from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from krcn_core.repository_context import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["--repo", str(REPO_ROOT), *sys.argv[1:]]))

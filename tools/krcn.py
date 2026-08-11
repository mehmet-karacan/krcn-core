#!/usr/bin/env python3
"""Run the KRCN Core CLI without installing the package."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.cli.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Resolve the KRCN Core V1 immutable architecture contracts."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from krcn_core.architecture_contracts import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["--repo", str(REPO_ROOT), *sys.argv[1:]]))

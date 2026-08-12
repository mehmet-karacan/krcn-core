#!/usr/bin/env python3
"""Format or check every versioned JSON source document."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from krcn_core.json_documents import (  # noqa: E402
    JsonDocumentError,
    format_json_file,
)


def _tracked_json_files(repo_root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", "*.json"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return tuple(
        repo_root / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Format versioned KRCN Core JSON documents",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo.resolve()
    changed: list[str] = []
    try:
        for path in _tracked_json_files(repo_root):
            if format_json_file(path, check=args.check):
                changed.append(path.relative_to(repo_root).as_posix())
    except (JsonDocumentError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.check and changed:
        for relative in changed:
            print(f"json-format: {relative}: formatting is required")
        return 1
    action = "checked" if args.check else "formatted"
    print(f"{len(_tracked_json_files(repo_root))} JSON documents {action}; {len(changed)} changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

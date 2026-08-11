#!/usr/bin/env python3
"""Run the full test suite with outbound network calls blocked."""

from __future__ import annotations

import socket
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def _network_blocked(*args: object, **kwargs: object) -> None:
    raise AssertionError("network access is prohibited during KRCN Core tests")


def main() -> int:
    suite = unittest.defaultTestLoader.discover(
        str(REPO_ROOT / "tests"),
        pattern="test_*.py",
    )
    with (
        patch.object(socket, "create_connection", _network_blocked),
        patch.object(socket.socket, "connect", _network_blocked),
        patch.object(socket.socket, "connect_ex", _network_blocked),
    ):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

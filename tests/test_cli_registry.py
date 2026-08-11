from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.cli.app import discover_repo_root, main  # noqa: E402
from krcn_core.repository_context import resolve_repository_context  # noqa: E402
from krcn_core.cli.registry import compatibility_registry  # noqa: E402


class CliRegistryTests(unittest.TestCase):
    def test_modular_registry_matches_reviewed_inventory(self) -> None:
        inventory = json.loads(
            (REPO_ROOT / ".ai" / "legacy-cli-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            item["id"]: (
                item["command"],
                item["visibility"],
                item["behavior"],
                item["disposition"],
            )
            for item in inventory["commands"]
        }
        actual = {
            item.command_id: (
                item.command,
                item.visibility,
                item.behavior,
                item.disposition,
            )
            for item in compatibility_registry().all()
        }
        self.assertEqual(expected, actual)

    def test_public_catalog_hides_internal_worker(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(["catalog", "--format", "json"])
        self.assertEqual(0, return_code)
        commands = json.loads(output.getvalue())
        self.assertEqual(28, len(commands))
        self.assertNotIn("index _worker", {item["command"] for item in commands})

    def test_internal_catalog_is_available_for_compatibility_checks(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(
                ["catalog", "--include-internal", "--format", "json"]
            )
        self.assertEqual(0, return_code)
        commands = json.loads(output.getvalue())
        self.assertEqual(29, len(commands))

    def test_cli_context_matches_shared_resolver(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(
                ["context", "--repo", str(REPO_ROOT), "--format", "json"]
            )
        self.assertEqual(0, return_code)
        expected = resolve_repository_context(REPO_ROOT).summary()
        self.assertEqual(expected, json.loads(output.getvalue()))

    def test_repository_root_is_discovered_from_nested_directory(self) -> None:
        nested = REPO_ROOT / "src" / "krcn_core" / "cli"
        self.assertEqual(REPO_ROOT, discover_repo_root(nested))


if __name__ == "__main__":
    unittest.main()

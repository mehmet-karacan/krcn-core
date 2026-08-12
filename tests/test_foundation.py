from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from krcn_core.foundation import (  # noqa: E402
    load_json,
    scan_tree,
    validate_json_documents,
    validate_foundation,
    validate_ownership_manifest,
    validate_provider_policy,
    verify_repository,
)


class FoundationConfigurationTests(unittest.TestCase):
    def test_foundation_configuration_is_valid(self) -> None:
        self.assertEqual([], validate_foundation(REPO_ROOT))

    def test_repository_scan_is_clean(self) -> None:
        self.assertEqual([], verify_repository(REPO_ROOT))

    def test_repository_json_documents_are_readable_and_valid(self) -> None:
        paths = [REPO_ROOT / item for item in ("config/ownership-manifest.json",)]
        self.assertEqual([], validate_json_documents(REPO_ROOT, paths))

    def test_ownership_defaults_preserve_unknown_paths(self) -> None:
        manifest = load_json(REPO_ROOT / "config" / "ownership-manifest.json")
        self.assertEqual("unmanaged", manifest["default_unmatched"]["ownership"])
        self.assertEqual("preserve", manifest["default_unmatched"]["merge_strategy"])
        self.assertTrue(manifest["default_unmatched"]["approval_required"])

    def test_ownership_rejects_runtime_replacement(self) -> None:
        manifest = load_json(REPO_ROOT / "config" / "ownership-manifest.json")
        changed = copy.deepcopy(manifest)
        runtime = next(item for item in changed["classes"] if item["id"] == "runtime")
        runtime["merge_strategy"] = "replace-managed"
        self.assertTrue(validate_ownership_manifest(changed))

    def test_provider_policy_rejects_implicit_remote_access(self) -> None:
        policy = load_json(REPO_ROOT / "config" / "provider-policy.json")
        changed = copy.deepcopy(policy)
        changed["remote_providers"]["enabled"] = True
        self.assertTrue(validate_provider_policy(changed))


class ImportBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_json(REPO_ROOT / "config" / "import-policy.json")

    def _scan_text(self, filename: str, text: str):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / filename).write_text(text, encoding="utf-8")
            return scan_tree(root, self.policy)

    def test_clean_portable_file_passes(self) -> None:
        self.assertEqual([], self._scan_text("portable.py", "print('portable')\n"))

    def test_windows_absolute_path_is_blocked(self) -> None:
        value = "C:" + "\\\\Users\\\\sample\\\\project"
        findings = self._scan_text("config.txt", value)
        self.assertIn("windows-absolute-path", {finding.code for finding in findings})

    def test_github_token_is_blocked(self) -> None:
        value = "github" + "_pat_" + "SYNTHETICVALUE"
        findings = self._scan_text("credential.txt", value)
        self.assertIn("github-token", {finding.code for finding in findings})

    def test_generic_secret_assignment_is_blocked(self) -> None:
        key = "api" + "_key"
        value = key + "=" + "SYNTHETICSECRET12345"
        findings = self._scan_text("settings.txt", value)
        self.assertIn("generic-secret-assignment", {finding.code for finding in findings})

    def test_unicode_long_dash_is_blocked(self) -> None:
        findings = self._scan_text("document.md", "left" + chr(0x2014) + "right")
        self.assertIn("unicode-long-dash", {finding.code for finding in findings})

    def test_database_file_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.db").write_bytes(b"database")
            findings = scan_tree(root, self.policy)
        self.assertIn("blocked-path", {finding.code for finding in findings})

    def test_policy_is_valid_json(self) -> None:
        path = REPO_ROOT / "config" / "import-policy.json"
        self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_schema_documents_are_valid_json(self) -> None:
        for path in sorted((REPO_ROOT / "schemas").glob("*.json")):
            with self.subTest(path=path.name):
                self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()

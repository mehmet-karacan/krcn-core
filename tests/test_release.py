from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.foundation import load_json  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.release import (  # noqa: E402
    ReleaseError,
    manifest_sha256,
    parse_release_manifest,
    validate_release_bundle,
)


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.payload_root = self.root / "payload"
        self.payload_root.mkdir()
        self.content = b"Updated core\n"
        (self.payload_root / "README.md").write_bytes(self.content)
        self.manifest = {
            "schema_ref": "schemas/release-manifest.schema.json",
            "schema_version": 1,
            "release_id": "krcn-core-0.2.0",
            "core_version": "0.2.0",
            "compatibility": {
                "minimum_core_version": "0.1.0",
                "maximum_core_version": "0.1.9",
            },
            "source_commit": "b" * 40,
            "files": [
                {
                    "path": "README.md",
                    "operation": "upsert",
                    "sha256": hashlib.sha256(self.content).hexdigest(),
                    "size": len(self.content),
                }
            ],
            "migrations": [],
            "derived_actions": [],
        }
        self.manifest_path = self.root / "release-manifest.json"
        self._write_manifest()
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.import_policy = load_json(REPO_ROOT / "config" / "import-policy.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _validate(self, trusted_digest: str | None = None):
        return validate_release_bundle(
            self.root,
            self.ownership,
            trusted_manifest_sha256=trusted_digest
            or manifest_sha256(self.manifest),
            installed_core_version="0.1.0",
            import_policy=self.import_policy,
        )

    def test_trusted_compatible_release_is_valid_and_redacted(self) -> None:
        bundle = self._validate()
        summary = bundle.public_summary()
        self.assertEqual("krcn-core-0.2.0", summary["release_id"])
        self.assertEqual({"upsert": 1, "delete": 0}, summary["file_counts"])
        self.assertNotIn(str(self.root), json.dumps(summary))

    def test_wrong_trust_digest_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "trusted digest"):
            self._validate("0" * 64)

    def test_payload_tampering_and_extra_files_are_rejected(self) -> None:
        (self.payload_root / "README.md").write_text(
            "Tampered core\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ReleaseError, "evidence"):
            self._validate()
        (self.payload_root / "README.md").write_bytes(self.content)
        (self.payload_root / "extra.txt").write_text("extra\n", encoding="utf-8")
        with self.assertRaisesRegex(ReleaseError, "do not match"):
            self._validate()

    def test_user_data_target_is_rejected_by_ownership(self) -> None:
        target = self.payload_root / ".krcn" / "projects" / "sample.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}\n", encoding="utf-8")
        (self.payload_root / "README.md").unlink()
        content = target.read_bytes()
        self.manifest["files"] = [
            {
                "path": ".krcn/projects/sample.json",
                "operation": "upsert",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        ]
        self._write_manifest()
        with self.assertRaisesRegex(ReleaseError, "core ownership"):
            self._validate()

    def test_incompatible_source_and_downgrade_are_rejected(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "outside release compatibility"):
            validate_release_bundle(
                self.root,
                self.ownership,
                trusted_manifest_sha256=manifest_sha256(self.manifest),
                installed_core_version="1.0.0",
                import_policy=self.import_policy,
            )
        changed = dict(self.manifest)
        changed["core_version"] = "0.0.9"
        changed["compatibility"] = {
            "minimum_core_version": "0.1.0",
            "maximum_core_version": "0.1.9",
        }
        self.manifest = changed
        self._write_manifest()
        with self.assertRaisesRegex(ReleaseError, "downgrade"):
            self._validate()

    def test_duplicate_path_and_invalid_compatibility_are_rejected(self) -> None:
        changed = dict(self.manifest)
        changed["files"] = self.manifest["files"] * 2
        with self.assertRaisesRegex(ReleaseError, "unique"):
            parse_release_manifest(changed)
        changed = dict(self.manifest)
        changed["compatibility"] = {
            "minimum_core_version": "1.0.0",
            "maximum_core_version": "0.1.0",
        }
        with self.assertRaisesRegex(ReleaseError, "range"):
            parse_release_manifest(changed)

    def test_secret_like_payload_is_rejected_by_safety_scan(self) -> None:
        secret_text = "api" + "_key=" + "SYNTHETICVALUE12345"
        content = secret_text.encode("utf-8")
        (self.payload_root / "README.md").write_bytes(content)
        self.manifest["files"][0]["sha256"] = hashlib.sha256(content).hexdigest()
        self.manifest["files"][0]["size"] = len(content)
        self._write_manifest()
        with self.assertRaisesRegex(ReleaseError, "safety scan"):
            self._validate()


if __name__ == "__main__":
    unittest.main()

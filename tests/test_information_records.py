from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.information_records import (  # noqa: E402
    InformationRecordError,
    parse_information_record,
    payload_digest,
    record_is_stale,
)


class InformationRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_digest = "a" * 64
        content = {
            "title": "Database access rule",
            "statement": "Only read operations are permitted",
            "labels": ["database", "policy-context"],
        }
        self.payload = {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": "database-read-rule",
            "information_class": "knowledge",
            "ownership": "user-data",
            "subject_ref": "project:sample/database",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "source-derived",
                "evidence": [
                    {
                        "source_ref": "policy:database-read-only",
                        "revision_id": "1",
                        "digest": self.source_digest,
                        "relation": "supports",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }

    def test_valid_record_preserves_revision_and_evidence(self) -> None:
        record = parse_information_record(self.payload)
        self.assertEqual("knowledge", record.information_class)
        self.assertEqual(1, record.revision)
        self.assertEqual(
            "policy:database-read-only",
            record.provenance.evidence[0].source_ref,
        )
        self.assertNotIn("payload", record.public_summary())

    def test_content_digest_tampering_is_rejected(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["payload"]["statement"] = "Delete is permitted"
        with self.assertRaisesRegex(InformationRecordError, "does not match"):
            parse_information_record(changed)

    def test_secret_like_keys_values_and_references_are_rejected(self) -> None:
        secret_key = "api" + "_key"
        secret_value = "pass" + "word=" + "synthetic-value"
        secret_ref = "key" + "ring://sample/credential"
        variants = (
            {secret_key: "placeholder"},
            {"value": secret_value},
            {"value": secret_ref},
        )
        for content in variants:
            with self.subTest(content=content):
                changed = copy.deepcopy(self.payload)
                changed["payload"] = content
                changed["content_digest"] = payload_digest(content)
                with self.assertRaisesRegex(InformationRecordError, "secret-like"):
                    parse_information_record(changed)

    def test_information_class_cannot_cross_ownership_boundary(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["ownership"] = "derived"
        with self.assertRaisesRegex(InformationRecordError, "ownership"):
            parse_information_record(changed)

    def test_evidence_required_class_cannot_drop_provenance(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["provenance"]["evidence"] = []
        with self.assertRaisesRegex(InformationRecordError, "requires"):
            parse_information_record(changed)

    def test_physical_and_parent_paths_are_not_logical_references(self) -> None:
        windows_path = "C" + ":\\sample\\project"
        for subject_ref in (
            windows_path,
            "project:sample/../other",
            "file:///sample/project",
        ):
            with self.subTest(subject_ref=subject_ref):
                changed = copy.deepcopy(self.payload)
                changed["subject_ref"] = subject_ref
                with self.assertRaisesRegex(
                    InformationRecordError,
                    "logical reference|portable",
                ):
                    parse_information_record(changed)

    def test_source_revision_change_marks_dependent_record_stale(self) -> None:
        record = parse_information_record(self.payload)
        self.assertFalse(
            record_is_stale(
                record,
                {"policy:database-read-only": ("1", self.source_digest)},
            )
        )
        self.assertTrue(
            record_is_stale(
                record,
                {"policy:database-read-only": ("2", "b" * 64)},
            )
        )
        self.assertTrue(record_is_stale(record, {}))

    def test_authoritative_source_is_superseded_not_marked_stale(self) -> None:
        content = {"binding_ref": "binding:sample-source"}
        changed = copy.deepcopy(self.payload)
        changed.update(
            {
                "record_id": "sample-source",
                "information_class": "authoritative-source",
                "subject_ref": "source:sample-source",
                "content_digest": payload_digest(content),
                "lifecycle": "stale",
                "payload": content,
            }
        )
        with self.assertRaisesRegex(InformationRecordError, "superseded"):
            parse_information_record(changed)


if __name__ == "__main__":
    unittest.main()

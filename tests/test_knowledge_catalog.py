from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.information_records import (  # noqa: E402
    parse_information_record,
    payload_digest,
)
from krcn_core.knowledge_catalog import (  # noqa: E402
    KnowledgeCatalogError,
    build_information_catalog,
)
from krcn_core.local_store import LocalStoreError, LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.source_bindings import parse_source_binding  # noqa: E402


def source_binding(*, revision: int = 1, source_id: str = "sample-project"):
    return parse_source_binding(
        {
            "schema_version": 1,
            "binding_id": "sample-project-local",
            "source_id": source_id,
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": "synthetic-fixture"},
            "default_access": "read-only",
            "capabilities": ["read", "metadata", "search"],
            "policy_refs": ["project-read-only"],
            "revision": revision,
        }
    )


def source_record(
    *,
    record_id: str = "sample-project-source",
    record_revision: int = 1,
    source_revision: str = "rev-1",
    source_digest: str = "a" * 64,
):
    content = {
        "title": "Sample project source",
        "source_id": "sample-project",
        "binding_id": "sample-project-local",
        "binding_revision": 1,
        "source_revision_id": source_revision,
        "source_digest": source_digest,
        "aliases": ["sample"],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": record_id,
            "information_class": "authoritative-source",
            "ownership": "user-data",
            "subject_ref": "source:sample-project",
            "revision": record_revision,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "system-observation",
                "evidence": [
                    {
                        "source_ref": "source:sample-project",
                        "revision_id": source_revision,
                        "digest": source_digest,
                        "relation": "observed-at",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


def knowledge_record(
    *,
    source_revision: str = "rev-1",
    source_digest: str = "a" * 64,
):
    content = {
        "title": "Database access rule",
        "text": "Only read operations are permitted",
        "keywords": ["database", "read-only"],
        "aliases": ["database rule"],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": "database-read-rule",
            "information_class": "knowledge",
            "ownership": "user-data",
            "subject_ref": "project:sample-project/database",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "source-derived",
                "evidence": [
                    {
                        "source_ref": "source:sample-project",
                        "revision_id": source_revision,
                        "digest": source_digest,
                        "relation": "supports",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


class KnowledgeCatalogTests(unittest.TestCase):
    def test_catalog_links_binding_and_orders_by_authority(self) -> None:
        source = source_record()
        knowledge = knowledge_record()
        first = build_information_catalog(
            [source_binding()],
            [knowledge, source],
        )
        second = build_information_catalog(
            [source_binding()],
            [source, knowledge],
        )
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(
            ["authoritative-source", "knowledge"],
            [entry.record.information_class for entry in first.entries],
        )
        self.assertTrue(all(entry.availability == "current" for entry in first.entries))
        public = json.dumps(first.as_dict())
        self.assertNotIn("synthetic-fixture", public)
        self.assertNotIn("Only read operations", public)

    def test_source_revision_change_marks_curated_knowledge_stale(self) -> None:
        catalog = build_information_catalog(
            [source_binding()],
            [
                source_record(source_revision="rev-2", source_digest="b" * 64),
                knowledge_record(),
            ],
        )
        self.assertEqual("current", catalog.get("sample-project-source").availability)
        self.assertEqual("stale", catalog.get("database-read-rule").availability)

    def test_missing_or_changed_binding_is_visible_without_locator_disclosure(self) -> None:
        missing = build_information_catalog([], [source_record(), knowledge_record()])
        self.assertEqual(
            "binding-missing",
            missing.get("sample-project-source").availability,
        )
        self.assertEqual("stale", missing.get("database-read-rule").availability)

        changed = build_information_catalog(
            [source_binding(revision=2)],
            [source_record(), knowledge_record()],
        )
        self.assertEqual(
            "binding-stale",
            changed.get("sample-project-source").availability,
        )

    def test_conflicting_current_sources_for_one_subject_are_rejected(self) -> None:
        with self.assertRaisesRegex(KnowledgeCatalogError, "only one current"):
            build_information_catalog(
                [source_binding()],
                [
                    source_record(),
                    source_record(record_id="another-project-source"),
                ],
            )

    def test_authoritative_source_requires_exact_revision_evidence(self) -> None:
        payload = source_record().as_payload()
        payload["provenance"]["evidence"][0]["revision_id"] = "other-revision"
        changed = parse_information_record(payload)
        with self.assertRaisesRegex(KnowledgeCatalogError, "exact source revision"):
            build_information_catalog([source_binding()], [changed])

    def test_catalog_rejects_unrelated_information_classes(self) -> None:
        payload = knowledge_record().as_payload()
        payload.update({"information_class": "derived", "ownership": "derived"})
        unrelated = parse_information_record(payload)
        with self.assertRaisesRegex(KnowledgeCatalogError, "accepts only"):
            build_information_catalog([], [unrelated])

    def test_catalog_revalidates_records_after_parsing(self) -> None:
        record = knowledge_record()
        record.payload["text"] = "Changed after digest verification"
        with self.assertRaisesRegex(KnowledgeCatalogError, "record is invalid"):
            build_information_catalog([source_binding()], [record])

    def test_regular_knowledge_record_cannot_smuggle_a_structured_profile(self) -> None:
        payload = knowledge_record().as_payload()
        content = dict(payload["payload"])
        content["profile"] = {"source_content": "must not be persisted"}
        payload["payload"] = content
        payload["content_digest"] = payload_digest(content)
        record = parse_information_record(payload)
        with self.assertRaisesRegex(KnowledgeCatalogError, "payload fields"):
            build_information_catalog([source_binding()], [record])


class CatalogPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(Path(self.temporary.name), ownership)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def authorize(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "synthetic-test-approval",
                approved=True,
            ),
        )

    def test_catalog_records_use_approved_preserved_user_data_collections(self) -> None:
        for collection, record in (
            ("authoritative-sources", source_record()),
            ("knowledge", knowledge_record()),
        ):
            with self.subTest(collection=collection):
                plan = self.store.prepare_put(
                    collection,
                    record.record_id,
                    record.as_payload(),
                    expected_revision=0,
                )
                self.assertEqual("user-data", plan.mutation.ownership)
                self.assertTrue(plan.mutation.approval_required)
                stored = self.store.apply_put(plan, self.authorize(plan))
                self.assertEqual(record.record_id, stored.record_id)

    def test_information_revision_must_match_store_revision(self) -> None:
        payload = knowledge_record().as_payload()
        payload["revision"] = 2
        with self.assertRaisesRegex(LocalStoreError, "planned record revision"):
            self.store.prepare_put(
                "knowledge",
                "database-read-rule",
                payload,
                expected_revision=0,
            )

    def test_knowledge_catalog_paths_are_preserved_user_data(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "config" / "ownership-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        user_data = next(item for item in manifest["classes"] if item["id"] == "user-data")
        self.assertIn(".krcn/knowledge/**", user_data["paths"])


if __name__ == "__main__":
    unittest.main()

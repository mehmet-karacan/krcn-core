from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.information_records import parse_information_record, payload_digest  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.memory_gate import memory_action_digest, parse_memory_action  # noqa: E402
from krcn_core.memory_hygiene import (  # noqa: E402
    MemoryHygieneError,
    build_context_effectiveness,
    build_memory_hygiene_report,
    build_memory_metadata_overlay,
    build_research_evidence_metadata,
    group_research_evidence_duplicates,
    load_memory_hygiene_policy,
    parse_context_effectiveness,
    parse_memory_hygiene_report,
    prepare_reviewed_memory_action,
)
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)


class MemoryHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_memory_hygiene_policy(REPO_ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.resolver = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.root, self.resolver)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def metadata(
        memory_id: str,
        *,
        semantic: str,
        created_at: str = "2025-01-01T00:00:00Z",
        valid_from=None,
        valid_until=None,
        last_used_at=None,
        usage_count: int = 0,
        retention_review_at=None,
        conflicts=(),
        content_digest: str | None = None,
    ):
        return build_memory_metadata_overlay(
            memory_id=memory_id,
            revision=1,
            content_digest=content_digest or hashlib.sha256(memory_id.encode()).hexdigest(),
            semantic_digest=semantic * 64,
            created_at=created_at,
            valid_from=valid_from,
            valid_until=valid_until,
            last_used_at=last_used_at,
            usage_count=usage_count,
            retention_review_at=retention_review_at,
            conflict_refs=list(conflicts),
            lifecycle="current",
            reviewed_by_ref="actor:memory-reviewer",
            review_digest="e" * 64,
        )

    @staticmethod
    def context(*, compaction: bool = True, stale: int = 0):
        return build_context_effectiveness(
            load_memory_hygiene_policy(REPO_ROOT),
            evaluation_id="context-evaluation",
            required_evidence_refs=["evidence:one", "evidence:two"],
            recalled_evidence_refs=["evidence:one", "evidence:two"],
            selected_bytes=1000,
            used_bytes=800,
            selected_tokens=250,
            used_tokens=200,
            selected_count=10,
            stale_selected_count=stale,
            duplicate_selected_count=0,
            omitted_required_count=0,
            downstream_success_basis_points=10000,
            compaction_rehydration_passed=compaction,
        )

    def test_temporal_conflict_duplicate_unused_and_retention_candidates(self) -> None:
        memories = [
            self.metadata("memory-one", semantic="a", last_used_at="2026-08-01T00:00:00Z", usage_count=3),
            self.metadata("memory-two", semantic="a", valid_until="2026-01-01T00:00:00Z"),
            self.metadata("memory-three", semantic="b", conflicts=["memory-one"]),
            self.metadata("memory-future", semantic="c", valid_from="2027-01-01T00:00:00Z"),
        ]
        report = build_memory_hygiene_report(
            self.policy, memories, [], [self.context()],
            report_id="hygiene-report", as_of="2026-08-16T00:00:00Z",
        )
        self.assertIn("memory-two", report["stale_memory_ids"])
        self.assertIn("memory-three", report["conflict_memory_ids"])
        self.assertIn("memory-two", report["unused_memory_ids"])
        self.assertIn("memory-two", report["retention_candidate_ids"])
        self.assertIn("memory-future", report["not_yet_valid_memory_ids"])
        self.assertEqual("memory-one", report["duplicate_groups"][0]["canonical_memory_id"])
        suggestions = {item["memory_id"]: item for item in report["action_suggestions"]}
        self.assertEqual("supersede", suggestions["memory-two"]["action"])
        self.assertEqual("memory:memory-one", suggestions["memory-two"]["replacement_ref"])
        self.assertFalse(report["invariants"]["automatic_delete_performed"])
        self.assertFalse(report["invariants"]["automatic_merge_performed"])

    def test_duplicate_video_28_29_has_single_evidence_weight(self) -> None:
        first = build_research_evidence_metadata(
            evidence_id="avenox-video-28",
            canonical_source_ref="video:TyG4ylryRfU",
            content_digest="a" * 64,
            observed_at="2026-08-15T00:00:00Z",
        )
        second = build_research_evidence_metadata(
            evidence_id="avenox-video-29",
            canonical_source_ref="video:TyG4ylryRfU",
            content_digest="a" * 64,
            observed_at="2026-08-15T00:00:01Z",
        )
        groups = group_research_evidence_duplicates([second, first])
        self.assertEqual(1, len(groups))
        self.assertEqual("avenox-video-28", groups[0]["canonical_evidence_id"])
        self.assertEqual(1, groups[0]["canonical_evidence_weight"])
        self.assertEqual(0, groups[0]["duplicate_of_suggestions"][0]["evidence_weight"])
        self.assertEqual("avenox-video-28", groups[0]["duplicate_of_suggestions"][0]["duplicate_of"])

    def test_context_effectiveness_measures_recall_use_noise_success_and_compaction(self) -> None:
        passed = self.context()
        self.assertTrue(passed.passed)
        self.assertEqual(10000, passed.metrics["required_evidence_recall_basis_points"])
        failed = self.context(compaction=False)
        self.assertFalse(failed.passed)
        stale = self.context(stale=1)
        self.assertFalse(stale.passed)
        tampered = copy.deepcopy(passed.as_payload())
        tampered["metrics"]["used_bytes_basis_points"] = 9999
        with self.assertRaises(MemoryHygieneError):
            parse_context_effectiveness(tampered)

    def test_report_is_digest_bound_and_performs_no_mutation(self) -> None:
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        report = build_memory_hygiene_report(
            self.policy,
            [self.metadata("memory-one", semantic="a")],
            [],
            [self.context()],
            report_id="hygiene-report",
            as_of="2026-08-16T00:00:00Z",
        )
        after = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertTrue(report["invariants"]["memory_gate_required"])
        self.assertFalse(report["invariants"]["grants_authority"])
        tampered = copy.deepcopy(report)
        tampered["stale_memory_ids"] = []
        with self.assertRaisesRegex(MemoryHygieneError, "digest"):
            parse_memory_hygiene_report(tampered)

    def test_metadata_rejects_physical_path_and_secret_reference(self) -> None:
        with self.assertRaises(MemoryHygieneError):
            build_research_evidence_metadata(
                evidence_id="bad-evidence",
                canonical_source_ref="source:C:" + chr(92) + "private" + chr(92) + "file",
                content_digest="a" * 64,
                observed_at="2026-08-16T00:00:00Z",
            )
        with self.assertRaisesRegex(MemoryHygieneError, "secret"):
            build_research_evidence_metadata(
                evidence_id="bad-evidence",
                canonical_source_ref="source:token=abcdefgh",
                content_digest="a" * 64,
                observed_at="2026-08-16T00:00:00Z",
            )

    def _persist_memory(self):
        content = {
            "memory_type": "preference",
            "title": "Read only database",
            "text": "Use read-only database access",
            "scope_ref": "project:sample-project",
            "retention_purpose": "Preserve an approved operating preference",
            "sensitivity": "non-sensitive",
        }
        record = parse_information_record({
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": "memory-one",
            "information_class": "memory",
            "ownership": "user-data",
            "subject_ref": "memory:memory-one",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "explicit-user",
                "evidence": [{
                    "source_ref": "source:sample-project",
                    "revision_id": "rev-1",
                    "digest": "a" * 64,
                    "relation": "supports",
                }],
            },
            "lifecycle": "current",
            "payload": content,
        })
        write = self.store.prepare_put("memory", "memory-one", record.as_payload(), expected_revision=0)
        authorization = authorize_mutation(
            write.mutation,
            dry_run=DryRunEvidence(write.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(write.mutation.plan_id, "memory-create-approval", approved=True),
        )
        self.store.apply_put(write, authorization)
        return record

    def test_hygiene_suggestion_requires_separate_exact_memory_gate_plan(self) -> None:
        record = self._persist_memory()
        report = build_memory_hygiene_report(
            self.policy,
            [self.metadata("memory-one", semantic="a", valid_until="2026-01-01T00:00:00Z", content_digest=record.content_digest)],
            [], [], report_id="hygiene-report", as_of="2026-08-16T00:00:00Z",
        )
        suggestion_payload = next(item for item in report["action_suggestions"] if item["memory_id"] == "memory-one")
        from krcn_core.memory_hygiene import parse_hygiene_action_suggestion
        suggestion = parse_hygiene_action_suggestion(suggestion_payload)
        digest = memory_action_digest(
            "reviewed-revoke", "revoke", "memory-one", record.revision,
            record.content_digest, None, "hygiene-session", "hygiene-approval", True,
        )
        action = parse_memory_action({
            "schema_ref": "schemas/memory-action.schema.json",
            "schema_version": 1,
            "action_id": "reviewed-revoke",
            "action": "revoke",
            "memory_id": "memory-one",
            "expected_revision": record.revision,
            "expected_content_digest": record.content_digest,
            "replacement_ref": None,
            "session_id": "hygiene-session",
            "approval_id": "hygiene-approval",
            "approved": True,
            "action_digest": digest,
        })
        plan = prepare_reviewed_memory_action(self.store, suggestion, action)
        self.assertTrue(plan.write_plan.mutation.approval_required)
        self.assertEqual("user-data", plan.write_plan.mutation.ownership)
        wrong = copy.deepcopy(action.as_payload())
        wrong["expected_content_digest"] = "f" * 64
        wrong["action_digest"] = memory_action_digest(
            "reviewed-revoke", "revoke", "memory-one", record.revision,
            "f" * 64, None, "hygiene-session", "hygiene-approval", True,
        )
        with self.assertRaisesRegex(MemoryHygieneError, "does not match"):
            prepare_reviewed_memory_action(
                self.store, suggestion, parse_memory_action(wrong)
            )

    def test_public_contracts_match_strict_json_schemas(self) -> None:
        memory = self.metadata("memory-one", semantic="a")
        evidence = build_research_evidence_metadata(
            evidence_id="evidence-one",
            canonical_source_ref="video:TyG4ylryRfU",
            content_digest="a" * 64,
            observed_at="2026-08-16T00:00:00Z",
        )
        context = self.context()
        report = build_memory_hygiene_report(
            self.policy, [memory], [evidence], [context],
            report_id="hygiene-report", as_of="2026-08-16T00:00:00Z",
        )
        context_schema = json.loads(
            (REPO_ROOT / "schemas" / "context-effectiveness.schema.json").read_text(encoding="utf-8")
        )
        registry = Registry().with_resource(
            "context-effectiveness.schema.json", Resource.from_contents(context_schema)
        )
        payloads = (
            ("memory-hygiene-policy.schema.json", json.loads((REPO_ROOT / "config" / "memory-hygiene-policy.json").read_text(encoding="utf-8"))),
            ("memory-metadata-overlay.schema.json", memory.as_payload()),
            ("research-evidence-metadata.schema.json", evidence.as_payload()),
            ("context-effectiveness.schema.json", context.as_payload()),
            ("memory-hygiene-report.schema.json", report),
        )
        for name, payload in payloads:
            schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(
                [], list(Draft202012Validator(schema, registry=registry).iter_errors(payload)), name
            )


if __name__ == "__main__":
    unittest.main()

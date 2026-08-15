from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.continuity import (  # noqa: E402
    SNAPSHOT_HARD_LIMIT_BYTES,
    SNAPSHOT_SOFT_LIMIT_BYTES,
    ContinuityError,
    build_continuity_snapshot,
    build_journal_event,
    finalize_handoff,
    parse_continuity_snapshot,
    parse_finalized_handoff,
    parse_work_journal_event,
    verify_continuity_snapshot,
    verify_journal_chain,
)


def _schema(name: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _snapshot(**overrides: object):
    arguments: dict[str, object] = {
        "snapshot_id": "snapshot-1",
        "project_id": "gpu-fusion",
        "work_item_id": "request-893614",
        "goal": "Gelir payı değişikliğini kanıtla",
        "status": "running",
        "current_step": "Oracle metadata doğrulaması",
        "updated_at": "2026-08-15T14:00:00+03:00",
        "work_item_revision": 2,
        "completed_steps": ["Belgeleri sınıflandır"],
        "next_safe_actions": ["Yetkili oran kaynağını doğrula"],
        "decisions": ["Taslak SQL üretime uygulanmayacak"],
        "failed_attempts": ["Belge isimlerinden tablo tahmini reddedildi"],
        "known_errors": ["Yetkili tablo adı doğrulanmadı"],
        "open_risks": ["Oran ölçeği bilinmiyor"],
        "changed_artifacts": ["work-item revision 2"],
        "verification_refs": ["evidence-1"],
        "source_binding_refs": ["binding-gpu-fusion"],
        "state_digest": "a" * 64,
        "branch": "main",
        "baseline_commit": "2e4d23a",
        "current_commit": "9dac491",
    }
    arguments.update(overrides)
    return build_continuity_snapshot(**arguments)


class ContinuitySnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_matches_schema_and_grants_no_authority(self) -> None:
        snapshot = _snapshot()
        payload = snapshot.as_dict()

        self.assertEqual(
            [],
            list(
                Draft202012Validator(_schema("continuity-snapshot.schema.json"))
                .iter_errors(payload)
            ),
        )
        self.assertFalse(payload["grants_authority"])
        self.assertEqual(snapshot, parse_continuity_snapshot(payload))

    def test_snapshot_trims_old_details_and_never_exceeds_hard_limit(self) -> None:
        long_entries = [f"item-{index}-" + ("x" * 490) for index in range(80)]
        snapshot = _snapshot(
            completed_steps=long_entries,
            decisions=long_entries,
            failed_attempts=long_entries,
            known_errors=long_entries,
            open_risks=long_entries,
            changed_artifacts=long_entries,
            verification_refs=long_entries,
        )

        self.assertLessEqual(snapshot.byte_size, SNAPSHOT_HARD_LIMIT_BYTES)
        self.assertLessEqual(snapshot.byte_size, SNAPSHOT_SOFT_LIMIT_BYTES)
        self.assertGreater(snapshot.sections["completed_steps"].omitted_count, 0)

    def test_authoritative_revision_state_and_source_conflicts_are_reported(self) -> None:
        errors = verify_continuity_snapshot(
            _snapshot(),
            work_item_revision=3,
            completed_step_ids=(),
            state_digest="b" * 64,
            source_revision_changed=True,
        )

        self.assertEqual(4, len(errors))
        self.assertTrue(any("revision" in error for error in errors))
        self.assertTrue(any("state digest" in error for error in errors))
        self.assertTrue(any("source revision" in error for error in errors))
        self.assertTrue(any("claims steps" in error for error in errors))

    def test_snapshot_rejects_paths_credentials_and_unknown_fields(self) -> None:
        with self.assertRaisesRegex(ContinuityError, "machine-specific path"):
            _snapshot(goal="Log file=D:/private/run.log")
        with self.assertRaisesRegex(ContinuityError, "credential"):
            _snapshot(goal="api_key=not-a-real-value")

        payload = _snapshot().as_dict()
        payload["authorization_id"] = "b" * 64
        with self.assertRaisesRegex(ContinuityError, "unexpected authorization_id"):
            parse_continuity_snapshot(payload)


class WorkJournalTests(unittest.TestCase):
    def test_events_form_a_digest_linked_round_trip_chain(self) -> None:
        first = build_journal_event(
            event_id="event-1",
            work_item_id="request-893614",
            occurred_at="2026-08-15T11:00:00Z",
            actor="analysis-worker",
            kind="root-cause-found",
            summary="Oran kaynağı doğrulanmadan SQL kesinleştirilemez",
            evidence_refs=["evidence-1"],
        )
        second = build_journal_event(
            event_id="event-2",
            work_item_id="request-893614",
            occurred_at="2026-08-15T11:01:00Z",
            actor="verifier",
            kind="test-passed",
            summary="Kaynak çelişkisi fail-closed doğrulandı",
            evidence_refs=["verification-1"],
            previous=first,
        )

        validator = Draft202012Validator(_schema("work-journal-event.schema.json"))
        self.assertEqual([], list(validator.iter_errors(first.as_dict())))
        self.assertEqual([], list(validator.iter_errors(second.as_dict())))
        self.assertEqual(first, parse_work_journal_event(first.as_dict()))
        self.assertEqual(second, parse_work_journal_event(second.as_dict()))
        self.assertEqual([], verify_journal_chain([first, second]))

    def test_chain_rejects_tamper_cross_work_item_and_time_regression(self) -> None:
        first = build_journal_event(
            event_id="event-1",
            work_item_id="request-893614",
            occurred_at="2026-08-15T11:00:00Z",
            actor="worker",
            kind="step-completed",
            summary="İlk adım tamamlandı",
        )
        second = build_journal_event(
            event_id="event-2",
            work_item_id="defect-475658",
            occurred_at="2026-08-15T10:59:00Z",
            actor="worker",
            kind="step-completed",
            summary="İkinci adım tamamlandı",
            previous=first,
        )
        tampered = replace(second, previous_digest="b" * 64)

        errors = verify_journal_chain([first, tampered])
        self.assertTrue(any("another work item" in error for error in errors))
        self.assertTrue(any("time order" in error for error in errors))
        self.assertTrue(any("does not link" in error for error in errors))
        self.assertTrue(any("digest does not match" in error for error in errors))


class FinalizedHandoffTests(unittest.TestCase):
    def test_handoff_is_portable_schema_valid_and_requires_fresh_authority(self) -> None:
        snapshot = _snapshot(approval_state="fresh-authorization-required")
        handoff = finalize_handoff(
            snapshot,
            handoff_id="handoff-1",
            created_at="2026-08-15T14:10:00+03:00",
            pending_step_ids=["verify-metadata"],
            first_reads=["continuity-snapshot", "work-item"],
        )
        payload = handoff.as_dict()

        self.assertEqual(
            [],
            list(
                Draft202012Validator(_schema("finalized-handoff.schema.json"))
                .iter_errors(payload)
            ),
        )
        self.assertTrue(payload["requires_fresh_authorization"])
        self.assertFalse(payload["grants_authority"])
        self.assertFalse(payload["carries_active_lease"])
        self.assertNotIn("authorization_id", payload)
        self.assertNotIn("resume_token", payload)
        self.assertEqual(handoff, parse_finalized_handoff(payload))

    def test_handoff_rejects_authority_lease_and_non_boolean_flag(self) -> None:
        payload = finalize_handoff(
            _snapshot(),
            handoff_id="handoff-1",
            created_at="2026-08-15T11:10:00Z",
        ).as_dict()

        for field in ("grants_authority", "carries_active_lease"):
            changed = dict(payload)
            changed[field] = True
            with self.subTest(field=field), self.assertRaises(ContinuityError):
                parse_finalized_handoff(changed)

        changed = dict(payload)
        changed["requires_fresh_authorization"] = "false"
        with self.assertRaisesRegex(ContinuityError, "must be a boolean"):
            parse_finalized_handoff(changed)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.capability_registry import (  # noqa: E402
    CapabilityRegistryError,
    build_capability_registry,
    capability_record_digest,
    load_capability_registry,
    parse_capability_record,
    select_capability_records,
)


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(
            (REPO_ROOT / "config" / "capability-registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.registry = load_capability_registry(REPO_ROOT)

    def test_registry_is_revision_aware_and_covers_every_kind(self) -> None:
        self.assertEqual(3, self.registry.revision)
        self.assertEqual(
            {"adapter", "agent", "model", "secret-provider", "skill", "tool"},
            {item.kind for item in self.registry.records},
        )
        self.assertEqual(64, len(self.registry.registry_digest))
        for record in self.registry.records:
            self.assertEqual(64, len(record.record_digest))

    def test_selection_requires_explicit_records_and_grants_no_authority(self) -> None:
        selected = select_capability_records(
            self.registry,
            ["planner-agent", "intent-normalizer-skill"],
            ["intent.normalize", "plan.create"],
        )
        summary = selected.as_dict()
        self.assertFalse(summary["grants_authority"])
        self.assertEqual(
            ["intent-normalizer-skill", "planner-agent"],
            sorted(item["record_id"] for item in summary["record_refs"]),
        )
        with self.assertRaisesRegex(CapabilityRegistryError, "not found"):
            select_capability_records(
                self.registry,
                ["host-discovered-tool"],
                ["plan.create"],
            )

    def test_selection_fails_when_declared_records_do_not_cover_capability(self) -> None:
        with self.assertRaisesRegex(CapabilityRegistryError, "do not provide"):
            select_capability_records(
                self.registry,
                ["planner-agent"],
                ["record.write"],
            )

    def test_only_worker_agent_may_declare_write_effects(self) -> None:
        changed = copy.deepcopy(self.payload["records"][0])
        changed["side_effects"].append("write")
        changed["write_ownership"] = ["core"]
        changed["record_digest"] = capability_record_digest(changed)
        with self.assertRaisesRegex(CapabilityRegistryError, "only worker"):
            parse_capability_record(changed)

    def test_user_data_and_remote_effects_require_declared_approval(self) -> None:
        writer = next(
            copy.deepcopy(item)
            for item in self.payload["records"]
            if item["record_id"] == "local-store-writer-tool"
        )
        writer["approval_triggers"] = []
        writer["record_digest"] = capability_record_digest(writer)
        with self.assertRaisesRegex(CapabilityRegistryError, "user-data"):
            parse_capability_record(writer)

        model = next(
            copy.deepcopy(item)
            for item in self.payload["records"]
            if item["kind"] == "model"
        )
        model["provider_mode"] = "remote"
        model["side_effects"] = ["network"]
        model["record_digest"] = capability_record_digest(model)
        with self.assertRaisesRegex(CapabilityRegistryError, "network approval"):
            parse_capability_record(model)

    def test_registry_rejects_tampering_and_missing_kinds(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["records"][0]["capabilities"].append("policy.override")
        with self.assertRaisesRegex(CapabilityRegistryError, "digest does not match"):
            build_capability_registry(changed)
        missing = copy.deepcopy(self.payload)
        missing["records"] = [item for item in missing["records"] if item["kind"] != "model"]
        with self.assertRaisesRegex(CapabilityRegistryError, "every capability kind"):
            build_capability_registry(missing)


if __name__ == "__main__":
    unittest.main()

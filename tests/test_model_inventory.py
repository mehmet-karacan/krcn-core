from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.local_store import LocalStoreError, LocalWorkspaceStore  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.model_inventory import (  # noqa: E402
    ModelInventoryError,
    apply_model_inventory,
    build_model_inventory_record,
    list_model_inventory,
    parse_model_inventory_record,
    prepare_model_inventory,
)
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)


def text_model(model_ref: str = "qwen35-27b") -> dict[str, object]:
    return {
        "model_ref": model_ref,
        "provider_ref": "litellm",
        "model_id": "openai/Qwen/Qwen3.5-27B",
        "display_name": "Qwen3.5 27B",
        "modalities": ["text"],
        "supported_workloads": [
            "analysis",
            "architecture",
            "implementation",
            "verification",
        ],
        "client_refs": ["opencode"],
        "remote": True,
        "enabled": True,
    }


class ModelInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(Path(self.temporary.name), self.ownership)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def authorize(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "synthetic-model-inventory-approval",
                True,
            ),
        )

    def test_inventory_is_credential_free_exact_plan_user_data(self) -> None:
        plan = prepare_model_inventory(self.store, self.ownership, [text_model()])
        self.assertEqual(1, len(plan.effect_plans))
        self.assertEqual("user-data", plan.effect_plans[0].mutation.ownership)
        self.assertTrue(plan.effect_plans[0].mutation.approval_required)
        summary = plan.public_summary()
        self.assertFalse(summary["credential_values_included"])
        self.assertFalse(summary["endpoints_included"])
        authorization = {
            effect.mutation.plan_id: self.authorize(effect)
            for effect in plan.effect_plans
        }
        applied = apply_model_inventory(self.store, plan, authorization)
        self.assertEqual(1, len(applied))
        listed = list_model_inventory(self.store)
        self.assertEqual("qwen35-27b", listed[0]["model_ref"])
        self.assertFalse(listed[0]["credential_values_included"])
        self.assertFalse(listed[0]["endpoint_included"])

    def test_identical_inventory_is_no_op_and_change_increments_revision(self) -> None:
        first = prepare_model_inventory(self.store, self.ownership, [text_model()])
        apply_model_inventory(
            self.store,
            first,
            {item.mutation.plan_id: self.authorize(item) for item in first.effect_plans},
        )
        no_op = prepare_model_inventory(self.store, self.ownership, [text_model()])
        self.assertEqual((), no_op.effect_plans)
        changed = text_model()
        changed["client_refs"] = ["codex", "opencode"]
        update = prepare_model_inventory(self.store, self.ownership, [changed])
        self.assertEqual(2, update.records[0]["revision"])

    def test_secret_endpoint_and_unknown_fields_are_rejected(self) -> None:
        unsafe = text_model()
        unsafe["api_key"] = "synthetic-secret"
        with self.assertRaisesRegex(ModelInventoryError, "fields"):
            build_model_inventory_record(unsafe, revision=1)
        unsafe = text_model()
        unsafe["model_id"] = "https://private.example.test/v1/model"
        with self.assertRaisesRegex(ModelInventoryError, "endpoint"):
            build_model_inventory_record(unsafe, revision=1)
        unsafe = text_model()
        unsafe["endpoint"] = "https://private.example.test"
        with self.assertRaisesRegex(ModelInventoryError, "fields"):
            build_model_inventory_record(unsafe, revision=1)

    def test_tampered_digest_and_store_identity_are_rejected(self) -> None:
        record = build_model_inventory_record(text_model(), revision=1)
        tampered = copy.deepcopy(record)
        tampered["model_id"] = "openai/fabricated"
        with self.assertRaisesRegex(ModelInventoryError, "inconsistent"):
            parse_model_inventory_record(tampered)
        with self.assertRaises(LocalStoreError):
            self.store.prepare_put(
                "model-inventory",
                "another-model",
                record,
                expected_revision=0,
            )

    def test_embedding_model_requires_embedding_workload(self) -> None:
        entry = text_model("qwen-embedding")
        entry["modalities"] = ["embedding"]
        with self.assertRaisesRegex(ModelInventoryError, "embedding workload"):
            build_model_inventory_record(entry, revision=1)

    def test_shared_service_requires_exact_plan_and_exposes_candidate_health(self) -> None:
        service = KrcnApplicationService(REPO_ROOT, self.store)
        arguments = {"models": [text_model()]}
        planned = service.execute(ServiceRequest("codex", "model.inventory", arguments))
        self.assertEqual("planned", planned.status)
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            service.execute(
                ServiceRequest(
                    "codex",
                    "model.inventory",
                    arguments,
                    apply=True,
                    expected_plan_id="0" * 64,
                    approval_id="inventory-approval",
                )
            )
        applied = service.execute(
            ServiceRequest(
                "codex",
                "model.inventory",
                arguments,
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="inventory-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        listed = service.execute(ServiceRequest("claude", "model.list", {}))
        self.assertEqual("candidate", listed.data["models"][0]["health_state"])

    def test_layout_v2_model_records_are_global_only(self) -> None:
        root = Path(self.temporary.name)
        (root / "layout.json").write_bytes(user_home_layout_bytes())
        plan = prepare_model_inventory(self.store, self.ownership, [text_model()])
        self.assertEqual(
            root / "global" / "models" / "qwen35-27b.json",
            plan.effect_plans[0].target,
        )
        with self.assertRaisesRegex(LocalStoreError, "global-only"):
            self.store.prepare_put(
                "model-inventory",
                "qwen35-27b",
                plan.records[0],
                expected_revision=0,
                project_id="sample-project",
            )

    def test_disabled_inventory_is_reported_as_disabled_not_candidate(self) -> None:
        disabled = text_model()
        disabled["enabled"] = False
        service = KrcnApplicationService(REPO_ROOT, self.store)
        arguments = {"models": [disabled]}
        planned = service.execute(ServiceRequest("codex", "model.inventory", arguments))
        service.execute(
            ServiceRequest(
                "codex",
                "model.inventory",
                arguments,
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="inventory-approval",
            )
        )
        listed = service.execute(ServiceRequest("codex", "model.list", {}))
        self.assertEqual("disabled", listed.data["models"][0]["health_state"])


if __name__ == "__main__":
    unittest.main()

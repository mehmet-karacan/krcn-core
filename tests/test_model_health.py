from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.model_health import (  # noqa: E402
    ModelHealthError,
    ModelHealthObservation,
    OpenAICompatibleModelHealthProbe,
    build_model_health_record,
    health_effective_state,
    load_model_health_policy,
    parse_model_health_record,
    list_model_health,
    prepare_model_health_action,
)
from krcn_core.model_inventory import build_model_inventory_record  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.provider_gate import (  # noqa: E402
    ProviderAuthorization,
    create_provider_request,
)
from krcn_core.secret_provider import SecretLease  # noqa: E402


def entry() -> dict[str, object]:
    return {
        "model_ref": "qwen35-27b",
        "provider_ref": "litellm",
        "model_id": "openai/Qwen/Qwen3.5-27B",
        "display_name": "Qwen3.5 27B",
        "modalities": ["text"],
        "supported_workloads": ["analysis", "implementation", "verification"],
        "client_refs": ["opencode"],
        "remote": True,
        "enabled": True,
    }


class ModelHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(Path(self.temporary.name), self.ownership)
        self.model = build_model_inventory_record(entry(), revision=1)
        plan = self.store.prepare_put(
            "model-inventory",
            "qwen35-27b",
            self.model,
            expected_revision=0,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=ApprovalEvidence(plan.mutation.plan_id, "inventory", True),
        )
        self.store.apply_put(plan, authorization)
        self.policy = load_model_health_policy(REPO_ROOT)
        self.now = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_success_record_contains_metrics_but_no_prompt_response_or_secret(self) -> None:
        observation = ModelHealthObservation(True, True, True, True, 581, None)
        record = build_model_health_record(
            self.model,
            self.policy,
            observation,
            checked_at=self.now,
        )
        parsed = parse_model_health_record(record)
        self.assertEqual("health-passed", parsed["status"])
        self.assertEqual(581, parsed["latency_ms"])
        serialized = json.dumps(parsed)
        self.assertNotIn("KRCN_HEALTH_OK", serialized)
        self.assertNotIn("secret", serialized.casefold())

    def test_consecutive_failures_quarantine_then_cooldown_expires(self) -> None:
        failure = ModelHealthObservation(False, False, False, False, 30000, "timeout")
        first = build_model_health_record(
            self.model,
            self.policy,
            failure,
            checked_at=self.now,
        )
        self.assertEqual("health-failed", first["status"])
        second = build_model_health_record(
            self.model,
            self.policy,
            failure,
            checked_at=self.now + timedelta(minutes=1),
            previous=first,
        )
        self.assertEqual("quarantined", second["status"])
        self.assertEqual(
            "cooldown",
            health_effective_state(second, self.now + timedelta(minutes=2)),
        )
        self.assertEqual(
            "candidate",
            health_effective_state(second, self.now + timedelta(hours=2)),
        )

    def test_remote_probe_does_not_run_without_exact_provider_approval(self) -> None:
        calls = []

        def transport(*args):
            calls.append(args)
            return {
                "status": 200,
                "payload": {"choices": [{"message": {"content": "KRCN_HEALTH_OK"}}]},
            }

        lease = SecretLease("opencode", b"synthetic-secret", "a" * 64)
        probe = OpenAICompatibleModelHealthProbe(
            lambda reference: lease,
            "opencode://litellm/api-key",
            transport=transport,
        )
        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            model_health_probes={"litellm": probe},
        )
        arguments = {
            "model_ref": "qwen35-27b",
            "endpoint": "https://provider.example.test/v1",
            "retention_assumptions": "Synthetic test retention is unknown",
            "session_id": "health-session",
        }
        planned = service.execute(ServiceRequest("codex", "model.health", arguments))
        with self.assertRaisesRegex(ApplicationServiceError, "session approval"):
            service.execute(
                ServiceRequest(
                    "codex",
                    "model.health",
                    arguments,
                    apply=True,
                    expected_plan_id=planned.data["plan"]["plan_id"],
                )
            )
        self.assertEqual([], calls)

    def test_approved_service_probe_persists_only_sanitized_health(self) -> None:
        def transport(endpoint, api_key, model_id, prompt, timeout, modality):
            self.assertEqual(b"synthetic-secret", api_key)
            self.assertEqual("text", modality)
            return {
                "status": 200,
                "payload": {"choices": [{"message": {"content": "KRCN_HEALTH_OK"}}]},
            }

        lease = SecretLease("opencode", b"synthetic-secret", "a" * 64)
        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            model_health_probes={
                "litellm": OpenAICompatibleModelHealthProbe(
                    lambda reference: lease,
                    "opencode://litellm/api-key",
                    transport=transport,
                )
            },
        )
        arguments = {
            "model_ref": "qwen35-27b",
            "endpoint": "https://provider.example.test/v1",
            "retention_assumptions": "Synthetic test retention is unknown",
            "session_id": "health-session",
        }
        planned = service.execute(ServiceRequest("opencode", "model.health", arguments))
        applied = service.execute(
            ServiceRequest(
                "opencode",
                "model.health",
                arguments,
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="approved-health-probe",
            )
        )
        self.assertEqual("applied", applied.status)
        health = self.store.read("model-health", "qwen35-27b")
        self.assertIsNotNone(health)
        serialized = json.dumps(health.payload)
        self.assertNotIn("synthetic-secret", serialized)
        self.assertNotIn("KRCN_HEALTH_OK", serialized)
        self.assertNotIn("provider.example", serialized)

    def test_inventory_change_makes_prior_health_stale_and_resets_failures(self) -> None:
        failure = ModelHealthObservation(False, False, False, False, 1000, "timeout")
        previous = build_model_health_record(
            self.model,
            self.policy,
            failure,
            checked_at=self.now,
        )
        plan = self.store.prepare_put(
            "model-health",
            "qwen35-27b",
            previous,
            expected_revision=0,
        )
        self.store.apply_put(
            plan,
            authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            ),
        )
        changed_entry = entry()
        changed_entry["client_refs"] = ["codex", "opencode"]
        changed_model = build_model_inventory_record(changed_entry, revision=2)
        current = self.store.read("model-inventory", "qwen35-27b")
        update = self.store.prepare_put(
            "model-inventory",
            "qwen35-27b",
            changed_model,
            expected_revision=current.revision,
        )
        self.store.apply_put(
            update,
            authorize_mutation(
                update.mutation,
                dry_run=DryRunEvidence(update.mutation.plan_id, True),
                approval=ApprovalEvidence(update.mutation.plan_id, "update", True),
            ),
        )
        status = list_model_health(REPO_ROOT, self.store, now=self.now)[0]
        self.assertEqual("stale", status["effective_state"])
        next_record = build_model_health_record(
            changed_model,
            self.policy,
            failure,
            checked_at=self.now + timedelta(minutes=1),
            previous=previous,
        )
        self.assertEqual(1, next_record["consecutive_failures"])
        self.assertEqual(2, next_record["health_revision"])

    def test_embedding_probe_accepts_only_a_numeric_vector_shape(self) -> None:
        embedding_entry = entry()
        embedding_entry.update(
            {
                "model_ref": "qwen3-embedding",
                "model_id": "openai/Qwen/Qwen3-Embedding-0.6B",
                "display_name": "Qwen3 Embedding 0.6B",
                "modalities": ["embedding"],
                "supported_workloads": ["embedding"],
            }
        )
        model = build_model_inventory_record(embedding_entry, revision=1)
        lease = SecretLease("opencode", b"synthetic-secret", "a" * 64)

        def transport(endpoint, api_key, model_id, prompt, timeout, modality):
            self.assertEqual("embedding", modality)
            return {
                "status": 200,
                "payload": {"data": [{"embedding": [0.25, -0.5, 1]}]},
            }

        probe = OpenAICompatibleModelHealthProbe(
            lambda reference: lease,
            "opencode://litellm/api-key",
            transport=transport,
        )
        request = create_provider_request(
            provider="litellm",
            endpoint="https://provider.example.test/v1",
            data_categories=("synthetic-test",),
            operation_scope="model-health",
            retention_assumptions="Synthetic test retention is unknown",
            session_id="health-session",
            remote=True,
        )
        authorization = ProviderAuthorization(request, True)
        observation = probe.probe(model, self.policy, authorization)
        self.assertTrue(observation.available)
        self.assertTrue(observation.response_matches)

    def test_disabled_model_is_not_health_eligible(self) -> None:
        disabled_entry = entry()
        disabled_entry["enabled"] = False
        disabled = build_model_inventory_record(disabled_entry, revision=2)
        current = self.store.read("model-inventory", "qwen35-27b")
        plan = self.store.prepare_put(
            "model-inventory",
            "qwen35-27b",
            disabled,
            expected_revision=current.revision,
        )
        self.store.apply_put(
            plan,
            authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, True),
                approval=ApprovalEvidence(plan.mutation.plan_id, "disable", True),
            ),
        )
        with self.assertRaisesRegex(ModelHealthError, "disabled"):
            prepare_model_health_action(
                REPO_ROOT,
                self.store,
                "qwen35-27b",
                endpoint="https://provider.example.test/v1",
                retention_assumptions="Synthetic test retention is unknown",
                session_id="health-session",
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()

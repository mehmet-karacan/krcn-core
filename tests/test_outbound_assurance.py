from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from krcn_core.foundation import load_json
from krcn_core.outbound_assurance import (
    OutboundAssuranceError,
    create_provider_assurance_profile,
    create_secret_broker_ref,
    decide_outbound_data,
    load_outbound_assurance_policy,
    parse_outbound_data_decision,
    parse_provider_assurance_profile,
    parse_secret_broker_ref,
)
from krcn_core.provider_gate import (
    ProviderApproval,
    authorize_provider_request,
    create_provider_request,
    load_provider_gate_policy,
)


ROOT = Path(__file__).resolve().parents[1]
SHA = hashlib.sha256(b"evidence").hexdigest()


class OutboundAssuranceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_outbound_assurance_policy(ROOT)
        request = create_provider_request(
            provider="reviewed-provider",
            endpoint="logical-endpoint",
            data_categories=("confidential-ip",),
            operation_scope="research",
            retention_assumptions="no-training",
            session_id="session-1",
            remote=True,
        )
        provider_policy = load_provider_gate_policy(ROOT)
        self.authorization = authorize_provider_request(
            provider_policy,
            request,
            approval=ProviderApproval(request.request_id, "session-1", "approval-1", True),
        )
        self.profile = create_provider_assurance_profile(
            profile_id="reviewed-provider-current",
            provider_id="reviewed-provider",
            observed_at="2026-08-17T10:00:00Z",
            valid_until="2026-08-18T10:00:00Z",
            accepted_categories=("public", "internal", "confidential-ip"),
            retention_class="no-training",
            training_opt_out_verified=True,
            regional_processing_verified=True,
            canary_credential_test_passed=True,
            evidence_ref="evidence:provider-review-1",
            evidence_digest=SHA,
        )

    def test_profile_decision_and_secret_ref_follow_schemas(self) -> None:
        decision = decide_outbound_data(
            self.policy,
            self.authorization,
            payload_digest=SHA,
            data_categories=("confidential-ip",),
            evaluated_at="2026-08-17T11:00:00Z",
            assurance=self.profile,
        )
        broker = create_secret_broker_ref(
            broker_id="local-broker",
            secret_ref="secret:provider-credential",
            operation_scope="research",
            expires_at="2026-08-17T12:00:00Z",
        )
        records = (
            ("provider-assurance-profile.schema.json", self.profile.as_dict()),
            ("outbound-data-decision.schema.json", decision.as_dict()),
            ("secret-broker-ref.schema.json", broker.as_dict()),
        )
        for schema_name, payload in records:
            with self.subTest(schema=schema_name):
                schema = load_json(ROOT / "schemas" / schema_name)
                self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        self.assertEqual("allowed-remote", decision.verdict)
        self.assertFalse(decision.as_dict()["contains_payload"])
        self.assertFalse(broker.as_dict()["contains_secret_value"])

    def test_secret_remote_is_always_blocked(self) -> None:
        request = create_provider_request(
            provider="reviewed-provider", endpoint="logical-endpoint",
            data_categories=("secret",), operation_scope="research",
            retention_assumptions="no-training", session_id="session-2", remote=True,
        )
        auth = type(self.authorization)(request=request, approval_verified=True)
        decision = decide_outbound_data(
            self.policy, auth, payload_digest=SHA, data_categories=("secret",),
            evaluated_at="2026-08-17T11:00:00Z", assurance=None,
        )
        self.assertEqual("blocked", decision.verdict)
        self.assertEqual(("secret-remote-prohibited",), decision.reason_codes)

    def test_confidential_requires_current_matching_assurance_and_canary(self) -> None:
        missing = decide_outbound_data(
            self.policy, self.authorization, payload_digest=SHA,
            data_categories=("confidential-ip",), evaluated_at="2026-08-17T11:00:00Z",
        )
        self.assertEqual(("provider-assurance-required",), missing.reason_codes)
        stale = decide_outbound_data(
            self.policy, self.authorization, payload_digest=SHA,
            data_categories=("confidential-ip",), evaluated_at="2026-08-19T11:00:00Z",
            assurance=self.profile,
        )
        self.assertEqual("blocked", stale.verdict)
        self.assertIn("provider-assurance-stale", stale.reason_codes)
        failed_canary = create_provider_assurance_profile(
            **{
                **{k: v for k, v in self.profile.as_dict().items() if k in {
                    "profile_id", "provider_id", "observed_at", "valid_until",
                    "accepted_categories", "retention_class", "training_opt_out_verified",
                    "regional_processing_verified", "canary_credential_test_passed",
                    "evidence_ref", "evidence_digest",
                }},
                "canary_credential_test_passed": False,
            }
        )
        blocked = decide_outbound_data(
            self.policy, self.authorization, payload_digest=SHA,
            data_categories=("confidential-ip",), evaluated_at="2026-08-17T11:00:00Z",
            assurance=failed_canary,
        )
        self.assertIn("provider-canary-failed", blocked.reason_codes)

    def test_category_must_match_exact_provider_request(self) -> None:
        with self.assertRaisesRegex(OutboundAssuranceError, "do not match"):
            decide_outbound_data(
                self.policy, self.authorization, payload_digest=SHA,
                data_categories=("public",), evaluated_at="2026-08-17T11:00:00Z",
                assurance=self.profile,
            )

    def test_tamper_extra_fields_and_secret_value_shapes_fail_closed(self) -> None:
        profile = self.profile.as_dict()
        profile["extra"] = True
        with self.assertRaises(OutboundAssuranceError):
            parse_provider_assurance_profile(profile)
        decision = decide_outbound_data(
            self.policy, self.authorization, payload_digest=SHA,
            data_categories=("confidential-ip",), evaluated_at="2026-08-17T11:00:00Z",
            assurance=self.profile,
        ).as_dict()
        tampered = copy.deepcopy(decision)
        tampered["verdict"] = "blocked"
        with self.assertRaisesRegex(OutboundAssuranceError, "digest"):
            parse_outbound_data_decision(tampered)
        broker = create_secret_broker_ref(
            broker_id="local-broker", secret_ref="secret:credential",
            operation_scope="research", expires_at="2026-08-17T12:00:00Z",
        ).as_dict()
        broker["contains_secret_value"] = True
        with self.assertRaises(OutboundAssuranceError):
            parse_secret_broker_ref(broker)

    def test_local_provider_does_not_require_remote_assurance(self) -> None:
        request = create_provider_request(
            provider="deterministic-hashing", endpoint="local-process",
            data_categories=("internal",), operation_scope="embedding",
            retention_assumptions="local-only", session_id="session-local", remote=False,
        )
        auth = authorize_provider_request(load_provider_gate_policy(ROOT), request)
        decision = decide_outbound_data(
            self.policy, auth, payload_digest=SHA, data_categories=("internal",),
            evaluated_at="2026-08-17T11:00:00Z",
        )
        self.assertEqual("allowed-local", decision.verdict)


if __name__ == "__main__":
    unittest.main()

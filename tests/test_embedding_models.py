from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.embedding_adapter import (  # noqa: E402
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingAdapter,
    create_embedding_provider_request,
)
from krcn_core.embedding_models import (  # noqa: E402
    EmbeddingModelError,
    load_embedding_model_catalog,
    parse_embedding_integration,
    parse_embedding_model_catalog,
)
from krcn_core.integrations import parse_integration_metadata  # noqa: E402
from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    load_provider_gate_policy,
)
from krcn_core.secret_provider import (  # noqa: E402
    OpenCodeSecretProvider,
    SecretProviderError,
)


def integration_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "integration_id": "sample-embeddings",
        "adapter_id": "openai-compatible-embedding",
        "source_binding_ref": "sample-project-local",
        "status": "active",
        "configuration": {
            "endpoint": "https://embedding.example.test/v1",
            "model_profile_ids": ["qwen3-embedding-0-6b", "bge-m3"],
            "offline_fallback_id": "deterministic-hashing",
            "retention_assumptions": "Provider retention is unknown",
        },
        "secret_refs": {"api-key": "opencode://litellm/api-key"},
        "policy_refs": [],
        "revision": 1,
    }


class EmbeddingModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_embedding_model_catalog(REPO_ROOT)
        metadata = parse_integration_metadata(integration_payload())
        self.integration = parse_embedding_integration(metadata, self.catalog)
        self.policy = load_provider_gate_policy(REPO_ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Path(self.temporary.name) / "opencode.json"
        self.config.write_text(
            "\ufeff"
            + json.dumps(
                {
                    "provider": {
                        "litellm": {
                            "options": {"apiKey": "synthetic-secret-value"}
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.secret_provider = OpenCodeSecretProvider(self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reviewed_catalog_selects_qwen_then_bge_then_offline(self) -> None:
        self.assertEqual("qwen3-embedding-0-6b", self.catalog.default_profile_id)
        self.assertEqual(("bge-m3",), self.catalog.fallback_profile_ids)
        self.assertEqual(
            ["qwen3-embedding-0-6b", "bge-m3"],
            [item.profile_id for item in self.catalog.remote_order],
        )
        self.assertEqual("deterministic-hashing", self.catalog.offline_fallback_id)
        self.assertEqual(1024, self.catalog.profile("qwen3-embedding-0-6b").vector_dimensions)
        self.assertEqual(1024, self.catalog.profile("bge-m3").vector_dimensions)

    def test_catalog_rejects_unreviewed_fallback_order(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config" / "embedding-models.json").read_text(
                encoding="utf-8"
            )
        )
        changed = copy.deepcopy(payload)
        changed["default_profile_id"] = "bge-m3"
        with self.assertRaisesRegex(EmbeddingModelError, "primary"):
            parse_embedding_model_catalog(changed)

    def test_integration_contains_no_literal_secret_and_matches_catalog(self) -> None:
        summary = self.integration.public_summary()
        self.assertEqual(
            ["qwen3-embedding-0-6b", "bge-m3"],
            summary["model_profile_ids"],
        )
        self.assertFalse(summary["credential_reference_disclosed"])
        self.assertNotIn("synthetic-secret-value", json.dumps(summary))

    def test_opencode_secret_provider_reads_bom_without_disclosing_value(self) -> None:
        lease = self.secret_provider.resolve("opencode://litellm/api-key")
        self.assertEqual(b"synthetic-secret-value", lease.reveal())
        self.assertFalse(lease.public_summary()["value_disclosed"])
        self.assertNotIn("synthetic-secret-value", json.dumps(lease.public_summary()))
        with self.assertRaisesRegex(SecretProviderError, "invalid"):
            self.secret_provider.resolve("opencode://litellm/other")

    def test_remote_transport_is_not_called_without_exact_approval(self) -> None:
        calls = []

        def transport(endpoint, api_key, model_id, texts, timeout):
            calls.append((endpoint, api_key, model_id, texts, timeout))
            return {}

        adapter = OpenAICompatibleEmbeddingAdapter(
            self.catalog,
            self.integration,
            self.secret_provider,
            self.policy,
            transport=transport,
        )
        profile = self.catalog.profile("qwen3-embedding-0-6b")
        request = create_embedding_provider_request(
            profile,
            self.integration,
            data_category="synthetic-test",
            session_id="embedding-test-session",
        )
        with self.assertRaisesRegex(EmbeddingProviderError, "session approval"):
            adapter.embed(profile.profile_id, ["synthetic"], request, approval=None)
        self.assertEqual([], calls)

    def test_approved_response_is_validated_and_normalized(self) -> None:
        def transport(endpoint, api_key, model_id, texts, timeout):
            self.assertEqual(b"synthetic-secret-value", api_key)
            return {
                "data": [
                    {
                        "index": 0,
                        "embedding": [1.0] * 1024,
                    }
                ]
            }

        adapter = OpenAICompatibleEmbeddingAdapter(
            self.catalog,
            self.integration,
            self.secret_provider,
            self.policy,
            transport=transport,
        )
        profile = self.catalog.profile("qwen3-embedding-0-6b")
        request = create_embedding_provider_request(
            profile,
            self.integration,
            data_category="synthetic-test",
            session_id="embedding-test-session",
        )
        approval = ProviderApproval(
            request.request_id,
            request.session_id,
            "approved-synthetic-test",
            True,
        )
        result = adapter.embed(
            profile.profile_id,
            ["synthetic"],
            request,
            approval=approval,
        )
        self.assertEqual(1024, result.dimensions)
        self.assertAlmostEqual(1.0, sum(item * item for item in result.vectors[0]))
        self.assertFalse(result.public_summary()["credential_disclosed"])

    def test_primary_failure_uses_preapproved_bge_fallback(self) -> None:
        calls = []

        def transport(endpoint, api_key, model_id, texts, timeout):
            calls.append(model_id)
            if "Qwen3" in model_id:
                raise EmbeddingProviderError("synthetic primary failure")
            return {"data": [{"index": 0, "embedding": [1.0] * 1024}]}

        adapter = OpenAICompatibleEmbeddingAdapter(
            self.catalog,
            self.integration,
            self.secret_provider,
            self.policy,
            transport=transport,
        )
        requests = {
            profile.profile_id: create_embedding_provider_request(
                profile,
                self.integration,
                data_category="synthetic-test",
                session_id="embedding-test-session",
            )
            for profile in self.catalog.remote_order
        }
        approvals = {
            profile_id: ProviderApproval(
                request.request_id,
                request.session_id,
                "approved-fallback-chain",
                True,
            )
            for profile_id, request in requests.items()
        }
        result = adapter.embed_with_fallback(
            ["synthetic"],
            requests=requests,
            approvals=approvals,
        )
        self.assertEqual("bge-m3", result.profile_id)
        self.assertEqual(
            ("qwen3-embedding-0-6b", "bge-m3"),
            result.attempted_profile_ids,
        )
        self.assertEqual(
            [
                "openai/Qwen/Qwen3-Embedding-0.6B",
                "openai/BAAI/bge-m3",
            ],
            calls,
        )

    def test_fallback_refuses_missing_profile_approval(self) -> None:
        adapter = OpenAICompatibleEmbeddingAdapter(
            self.catalog,
            self.integration,
            self.secret_provider,
            self.policy,
            transport=lambda *args: {},
        )
        primary = self.catalog.remote_order[0]
        request = create_embedding_provider_request(
            primary,
            self.integration,
            data_category="synthetic-test",
            session_id="embedding-test-session",
        )
        with self.assertRaisesRegex(EmbeddingProviderError, "exact request"):
            adapter.embed_with_fallback(
                ["synthetic"],
                requests={primary.profile_id: request},
                approvals={},
            )


if __name__ == "__main__":
    unittest.main()

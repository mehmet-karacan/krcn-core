from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.embedding_models import load_embedding_model_catalog  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.model_routing import (  # noqa: E402
    ModelRoutingError,
    load_model_routing_policy,
    parse_model_routing_policy,
    resolve_model_route,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


class ModelRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_model_routing_policy(REPO_ROOT)

    def test_role_defaults_are_complete_and_client_neutral(self) -> None:
        self.assertEqual(
            {"planner", "worker", "verifier"},
            set(self.policy.role_defaults),
        )
        selection = resolve_model_route(self.policy, role="planner")
        self.assertEqual("planning-high", selection.profile_id)
        self.assertEqual("client-default", selection.selected_ref)
        self.assertEqual("client-default", selection.selection_basis)
        self.assertIsNone(selection.selected_model_id)
        self.assertFalse(selection.as_dict()["model_selection_grants_authority"])

    def test_available_client_slot_selects_the_client_model(self) -> None:
        selection = resolve_model_route(
            self.policy,
            workload="implementation",
            available_bindings={"client-coding-balanced": "vendor/coding-model"},
        )
        self.assertEqual("client-coding-balanced", selection.selected_ref)
        self.assertEqual("vendor/coding-model", selection.selected_model_id)
        self.assertEqual("client-binding", selection.selection_basis)

    def test_embedding_prefers_authorized_qwen_then_bge(self) -> None:
        bindings = {
            "qwen3-embedding-0-6b": "openai/Qwen/Qwen3-Embedding-0.6B",
            "bge-m3": "openai/BAAI/bge-m3",
        }
        primary = resolve_model_route(
            self.policy,
            workload="embedding",
            available_bindings=bindings,
            authorized_refs=("qwen3-embedding-0-6b", "bge-m3"),
        )
        self.assertEqual("qwen3-embedding-0-6b", primary.selected_ref)
        fallback = resolve_model_route(
            self.policy,
            workload="embedding",
            available_bindings=bindings,
            authorized_refs=("bge-m3",),
        )
        self.assertEqual("bge-m3", fallback.selected_ref)
        self.assertEqual(
            ("qwen3-embedding-0-6b",),
            fallback.skipped_unauthorized_refs,
        )

    def test_embedding_without_available_authorized_provider_is_offline(self) -> None:
        selection = resolve_model_route(self.policy, workload="embedding")
        self.assertEqual("deterministic-hashing", selection.selected_ref)
        self.assertEqual("deterministic-hashing", selection.selected_model_id)
        self.assertEqual("offline-fallback", selection.selection_basis)
        self.assertFalse(selection.as_dict()["provider_call_performed"])

    def test_unknown_binding_and_ambiguous_selector_fail_closed(self) -> None:
        with self.assertRaisesRegex(ModelRoutingError, "not declared"):
            resolve_model_route(
                self.policy,
                workload="planning",
                available_bindings={"unknown-slot": "vendor/model"},
            )
        with self.assertRaisesRegex(ModelRoutingError, "exactly one"):
            resolve_model_route(
                self.policy,
                workload="planning",
                role="planner",
            )
        with self.assertRaisesRegex(ModelRoutingError, "reviewed model catalog"):
            resolve_model_route(
                self.policy,
                workload="embedding",
                available_bindings={"qwen3-embedding-0-6b": "vendor/other-model"},
                authorized_refs=("qwen3-embedding-0-6b",),
            )

    def test_embedding_order_cannot_diverge_from_reviewed_catalog(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config" / "model-routing.json").read_text(
                encoding="utf-8"
            )
        )
        changed = copy.deepcopy(payload)
        embedding = next(
            profile
            for profile in changed["profiles"]
            if profile["workload"] == "embedding"
        )
        embedding["preferred_refs"][:2] = reversed(
            embedding["preferred_refs"][:2]
        )
        with self.assertRaisesRegex(ModelRoutingError, "disagrees"):
            parse_model_routing_policy(
                changed,
                load_embedding_model_catalog(REPO_ROOT),
            )

    def test_application_contract_is_identical_for_every_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / ".krcn"
            store = LocalWorkspaceStore(
                data_root,
                OwnershipResolver.from_repository(REPO_ROOT),
            )
            service = KrcnApplicationService(REPO_ROOT, store)
            responses = []
            for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
                response = service.execute(
                    ServiceRequest(
                        client,
                        "model.resolve",
                        {"role": "verifier"},
                    )
                )
                responses.append(response.data)
            self.assertTrue(all(response == responses[0] for response in responses))
            with self.assertRaisesRegex(ApplicationServiceError, "read-only"):
                service.execute(
                    ServiceRequest(
                        "cli",
                        "model.resolve",
                        {"role": "verifier"},
                        apply=True,
                    )
                )

    def test_cli_resolves_default_without_client_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "model",
                        "resolve",
                        "--role",
                        "worker",
                        "--repo",
                        str(REPO_ROOT),
                        "--data-root",
                        str(Path(temporary) / ".krcn"),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(0, result)
            payload = json.loads(output.getvalue())
            self.assertEqual(
                "client-default",
                payload["data"]["selection"]["selected_ref"],
            )


if __name__ == "__main__":
    unittest.main()

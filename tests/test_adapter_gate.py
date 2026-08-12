from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.adapter_gate import (  # noqa: E402
    AdapterApproval,
    AdapterGateError,
    authorize_adapter_operation,
    parse_adapter_descriptor,
    prepare_adapter_operation,
)
from krcn_core.policies import parse_user_policy  # noqa: E402
from krcn_core.source_bindings import parse_source_binding  # noqa: E402


def descriptor():
    payload = json.loads(
        (
            REPO_ROOT / ".ai" / "registry" / "adapters" / "local-discovery.json"
        ).read_text(encoding="utf-8")
    )
    return parse_adapter_descriptor(payload)


def binding(*, capabilities=None, policy_refs=None):
    return parse_source_binding(
        {
            "schema_version": 1,
            "binding_id": "sample-project-local",
            "source_id": "sample-project",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": "synthetic-location"},
            "default_access": "read-only",
            "capabilities": capabilities or ["read", "metadata"],
            "policy_refs": policy_refs or [],
            "revision": 1,
        }
    )


def source_policy(effect: str):
    return parse_user_policy(
        {
            "schema_version": 1,
            "policy_id": f"source-{effect}",
            "scope": {"kind": "source", "ref": "sample-project"},
            "revision": 1,
            "rules": [
                {
                    "rule_id": f"{effect}-discovery",
                    "resource_type": "source",
                    "operations": ["discover"],
                    "effect": effect,
                    "provenance": {"kind": "explicit-user"},
                    "active": True,
                }
            ],
        }
    )


class AdapterGateTests(unittest.TestCase):
    def test_local_discovery_descriptor_is_valid(self) -> None:
        adapter = descriptor()
        self.assertEqual("local-discovery", adapter.adapter_id)
        operation = adapter.operation("discover")
        self.assertEqual({"read", "metadata"}, set(operation.required_capabilities))
        self.assertFalse(operation.mutation_effect)
        self.assertFalse(operation.network_effect)

    def test_local_source_code_adapter_is_read_only_and_offline(self) -> None:
        payload = json.loads(
            (
                REPO_ROOT
                / ".ai"
                / "registry"
                / "adapters"
                / "local-source-code.json"
            ).read_text(encoding="utf-8")
        )
        adapter = parse_adapter_descriptor(payload)
        self.assertEqual("local-source-code", adapter.adapter_id)
        self.assertEqual({"index", "retrieve"}, {
            item.operation_id for item in adapter.operations
        })
        self.assertTrue(all(not item.mutation_effect for item in adapter.operations))
        self.assertTrue(all(not item.network_effect for item in adapter.operations))

    def test_missing_capability_blocks_request(self) -> None:
        with self.assertRaisesRegex(AdapterGateError, "metadata"):
            prepare_adapter_operation(
                descriptor(), binding(capabilities=["read"]), "discover", []
            )

    def test_user_deny_overrides_adapter_default_allow(self) -> None:
        request = prepare_adapter_operation(
            descriptor(), binding(), "discover", [source_policy("deny")]
        )
        self.assertEqual("deny", request.policy_effect)
        with self.assertRaisesRegex(AdapterGateError, "denied"):
            authorize_adapter_operation(request)

    def test_require_approval_is_bound_to_exact_request(self) -> None:
        request = prepare_adapter_operation(
            descriptor(), binding(), "discover", [source_policy("require-approval")]
        )
        with self.assertRaisesRegex(AdapterGateError, "matching approval"):
            authorize_adapter_operation(request)
        authorization = authorize_adapter_operation(
            request,
            AdapterApproval(request.request_id, "approval-1", approved=True),
        )
        self.assertTrue(authorization.approval_verified)

    def test_missing_referenced_policy_blocks_request(self) -> None:
        with self.assertRaisesRegex(AdapterGateError, "unavailable policies"):
            prepare_adapter_operation(
                descriptor(),
                binding(policy_refs=["required-project-policy"]),
                "discover",
                [],
            )

    def test_no_policy_uses_safe_adapter_default(self) -> None:
        request = prepare_adapter_operation(descriptor(), binding(), "discover", [])
        self.assertEqual("allow", request.policy_effect)
        authorization = authorize_adapter_operation(request)
        self.assertFalse(authorization.approval_verified)


if __name__ == "__main__":
    unittest.main()

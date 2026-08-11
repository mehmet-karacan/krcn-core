from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    ProviderGateError,
    authorize_provider_request,
    create_provider_request,
    load_provider_gate_policy,
    select_default_provider,
)


class ProviderGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_provider_gate_policy(REPO_ROOT)

    def test_environment_does_not_select_a_remote_provider(self) -> None:
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "remote-provider"}):
            self.assertEqual(
                "deterministic-hashing", select_default_provider(self.policy)
            )

    def test_local_deterministic_provider_needs_no_remote_approval(self) -> None:
        request = create_provider_request(
            provider="deterministic-hashing",
            endpoint="local-process",
            data_categories=("synthetic-text",),
            operation_scope="test-index",
            retention_assumptions="No remote retention",
            session_id="test-session",
            remote=False,
        )
        authorization = authorize_provider_request(self.policy, request)
        self.assertFalse(authorization.approval_verified)

    def test_remote_provider_requires_exact_session_approval(self) -> None:
        request = create_provider_request(
            provider="approved-remote",
            endpoint="configured-endpoint",
            data_categories=("document-text", "query-text"),
            operation_scope="semantic-search",
            retention_assumptions="Provider terms reviewed by the user",
            session_id="session-1",
            remote=True,
        )
        with self.assertRaisesRegex(ProviderGateError, "session approval"):
            authorize_provider_request(self.policy, request)
        approval = ProviderApproval(
            request_id=request.request_id,
            session_id="session-1",
            approval_id="approval-1",
            approved=True,
        )
        authorization = authorize_provider_request(
            self.policy, request, approval=approval
        )
        self.assertTrue(authorization.approval_verified)

    def test_approval_from_another_session_is_rejected(self) -> None:
        request = create_provider_request(
            provider="approved-remote",
            endpoint="configured-endpoint",
            data_categories=("query-text",),
            operation_scope="semantic-search",
            retention_assumptions="Provider terms reviewed by the user",
            session_id="session-2",
            remote=True,
        )
        approval = ProviderApproval(
            request_id=request.request_id,
            session_id="another-session",
            approval_id="approval-2",
            approved=True,
        )
        with self.assertRaisesRegex(ProviderGateError, "session approval"):
            authorize_provider_request(self.policy, request, approval=approval)

    def test_public_summary_does_not_expose_endpoint(self) -> None:
        request = create_provider_request(
            provider="approved-remote",
            endpoint="private-configured-endpoint",
            data_categories=("query-text",),
            operation_scope="semantic-search",
            retention_assumptions="Provider terms reviewed by the user",
            session_id="session-3",
            remote=True,
        )
        summary = request.public_summary()
        self.assertTrue(summary["endpoint_disclosed"])
        self.assertNotIn("private-configured-endpoint", str(summary))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.client_bootstrap import (  # noqa: E402
    BEGIN_MARKER,
    END_MARKER,
    ClientBootstrapError,
    apply_client_bootstrap,
    prepare_client_bootstrap,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.request_authorization import mint_initiating_request_evidence  # noqa: E402


class ClientBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile"
        self.data_root = self.root / "shared-home"
        (self.profile / ".codex").mkdir(parents=True)
        (self.profile / ".config" / "opencode").mkdir(parents=True)
        self.codex = self.profile / ".codex" / "AGENTS.md"
        self.claude = self.profile / ".claude" / "CLAUDE.md"
        self.opencode = self.profile / ".config" / "opencode" / "AGENTS.md"
        self.codex.write_bytes(b"")
        self.opencode_original = b"# Existing OpenCode rules\r\n\r\n- Preserve this.\r\n"
        self.opencode.write_bytes(self.opencode_original)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def authorizations(plan):
        return {
            effect.plan_id: authorize_mutation(
                effect,
                dry_run=DryRunEvidence(effect.plan_id, True),
                approval=ApprovalEvidence(effect.plan_id, "bootstrap-approval", True),
            )
            for effect in plan.effect_plans
        }

    def test_apply_preserves_existing_content_and_creates_verified_backups(self) -> None:
        plan = prepare_client_bootstrap(
            self.profile,
            self.data_root,
            self.ownership,
        )
        summary = plan.public_summary()
        self.assertEqual(3, summary["client_count"])
        self.assertEqual(3, summary["change_count"])
        self.assertFalse(summary["paths_disclosed"])
        self.assertFalse(summary["existing_content_overwritten"])
        self.assertNotIn(str(self.profile), json.dumps(summary))

        result = apply_client_bootstrap(plan, self.authorizations(plan))

        self.assertEqual(
            ("codex", "claude-code", "opencode"),
            result.changed_clients,
        )
        for target in (self.codex, self.claude, self.opencode):
            content = target.read_text(encoding="utf-8")
            self.assertEqual(1, content.count(BEGIN_MARKER))
            self.assertEqual(1, content.count(END_MARKER))
        self.assertTrue(self.opencode.read_bytes().startswith(self.opencode_original))
        self.assertIn(
            "krcn model resolve",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            ".krcn/projects/<project-id>/local-data/client-artifacts/",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            ".krcn/global/local-data/client-artifacts/",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "explicit KRCN Core product-development request",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "krcn client delegation",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "main agent is coordinator-only",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "delegation-unavailable",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Research Actions",
            self.codex.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "detaylı araştır",
            self.codex.read_text(encoding="utf-8"),
        )
        for target in (self.codex, self.claude, self.opencode):
            guidance = target.read_text(encoding="utf-8")
            self.assertIn("Use quiet execution in every client", guidance)
            self.assertIn("raw JSON, stdout, or stderr", guidance)
            self.assertIn("verbose or debug output", guidance)
        for entry in plan.entries:
            if entry.existed:
                assert entry.backup_path is not None
                self.assertEqual(entry.original, entry.backup_path.read_bytes())

        repeated = prepare_client_bootstrap(
            self.profile,
            self.data_root,
            self.ownership,
        )
        self.assertEqual(0, repeated.public_summary()["change_count"])
        self.assertEqual((), repeated.effect_plans)

    def test_existing_managed_block_is_replaced_without_touching_other_text(self) -> None:
        original = (
            "# Personal\n\n"
            f"{BEGIN_MARKER}\nold rule\n{END_MARKER}\n\n"
            "# Keep\n"
        ).encode("utf-8")
        self.codex.write_bytes(original)
        plan = prepare_client_bootstrap(
            self.profile,
            self.data_root,
            self.ownership,
        )
        codex_entry = next(entry for entry in plan.entries if entry.client_id == "codex")
        rendered = codex_entry.rendered.decode("utf-8")
        self.assertTrue(rendered.startswith("# Personal\n\n"))
        self.assertTrue(rendered.endswith("\n\n# Keep\n"))
        self.assertNotIn("old rule", rendered)

    def test_new_managed_block_preserves_existing_bytes_exactly(self) -> None:
        original = b"# Personal rules\r\n\r\n\r\n"
        self.codex.write_bytes(original)
        plan = prepare_client_bootstrap(
            self.profile,
            self.data_root,
            self.ownership,
        )
        codex_entry = next(entry for entry in plan.entries if entry.client_id == "codex")
        self.assertTrue(codex_entry.rendered.startswith(original))
        self.assertEqual(original, codex_entry.rendered[: len(original)])

    def test_malformed_marker_fails_before_writes(self) -> None:
        self.codex.write_text(f"{BEGIN_MARKER}\nmissing end\n", encoding="utf-8")
        with self.assertRaisesRegex(ClientBootstrapError, "markers"):
            prepare_client_bootstrap(
                self.profile,
                self.data_root,
                self.ownership,
            )
        self.assertFalse(self.data_root.exists())

    def test_secret_like_existing_content_blocks_backup(self) -> None:
        self.opencode.write_text("token=abcdefghijklmnop\n", encoding="utf-8")
        with self.assertRaisesRegex(ClientBootstrapError, "secret-like"):
            prepare_client_bootstrap(
                self.profile,
                self.data_root,
                self.ownership,
            )
        self.assertFalse(self.data_root.exists())

    def test_stale_plan_fails_before_any_bootstrap_write(self) -> None:
        plan = prepare_client_bootstrap(
            self.profile,
            self.data_root,
            self.ownership,
        )
        self.opencode.write_bytes(self.opencode_original + b"changed\r\n")
        with self.assertRaisesRegex(ClientBootstrapError, "changed"):
            apply_client_bootstrap(plan, self.authorizations(plan))
        self.assertEqual(b"", self.codex.read_bytes())
        self.assertFalse(self.claude.exists())
        self.assertFalse(self.data_root.exists())

    def test_interrupted_write_restores_changed_client_files(self) -> None:
        plan = prepare_client_bootstrap(
            self.profile,
            self.data_root,
            self.ownership,
        )
        from krcn_core import client_bootstrap

        real_atomic_write = client_bootstrap._atomic_write

        def fail_on_claude(path: Path, content: bytes) -> None:
            if path.name == "CLAUDE.md":
                raise OSError("synthetic client write interruption")
            real_atomic_write(path, content)

        with patch("krcn_core.client_bootstrap._atomic_write", side_effect=fail_on_claude):
            with self.assertRaisesRegex(OSError, "interruption"):
                apply_client_bootstrap(plan, self.authorizations(plan))
        self.assertEqual(b"", self.codex.read_bytes())
        self.assertFalse(self.claude.exists())
        self.assertEqual(self.opencode_original, self.opencode.read_bytes())

    def test_all_application_clients_receive_the_same_plan(self) -> None:
        store = LocalWorkspaceStore(self.data_root, self.ownership)
        service = KrcnApplicationService(REPO_ROOT, store)
        plans = []
        with patch("krcn_core.application.Path.home", return_value=self.profile):
            for client in (
                "cli",
                "sdk",
                "mcp",
                "plugin",
                "codex",
                "claude",
                "opencode",
            ):
                response = service.execute(
                    ServiceRequest(client, "client.bootstrap", {})
                )
                self.assertEqual("planned", response.status)
                plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))

    def test_trusted_current_request_applies_bootstrap_without_second_approval(self) -> None:
        evidence = {}

        def trusted_host(request):
            evidence.setdefault(
                request.intent_request_id,
                mint_initiating_request_evidence(
                    session_id="codex-bootstrap-session",
                    intent_request_id=request.intent_request_id,
                    user_turn_digest="9" * 64,
                    source="trusted-host",
                ).as_dict(),
            )
            return evidence[request.intent_request_id]

        store = LocalWorkspaceStore(self.data_root, self.ownership)
        service = KrcnApplicationService(
            REPO_ROOT,
            store,
            trusted_request_evidence_provider=trusted_host,
        )
        with patch("krcn_core.application.Path.home", return_value=self.profile):
            planned = service.execute(ServiceRequest("codex", "client.bootstrap", {}))
            applied = service.execute(ServiceRequest(
                "codex",
                "client.bootstrap",
                {},
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
            ))
        self.assertEqual("applied", applied.status)
        self.assertEqual(
            "consumed", applied.data["authorization_receipt"]["status"]
        )


if __name__ == "__main__":
    unittest.main()

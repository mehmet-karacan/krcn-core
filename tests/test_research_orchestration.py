from __future__ import annotations

import json
import sys
import tempfile
import unittest
import os
import subprocess

from jsonschema import Draft202012Validator
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.research_orchestration import (  # noqa: E402
    ResearchOrchestrationError,
    apply_research_result_import,
    apply_research_run,
    get_research_status,
    prepare_research_result_import,
    prepare_research_run,
)


def authorize(plan):
    return authorize_mutation(
        plan,
        dry_run=DryRunEvidence(plan.plan_id, verified=True),
        approval=(
            ApprovalEvidence(plan.plan_id, "research-test-approval", approved=True)
            if plan.approval_required
            else None
        ),
    )


class ResearchOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        self.prepare_request = {
            "schema_ref": "schemas/research-run-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "title": "Provider independent research",
            "question": "Evaluate optional research providers.",
            "context": "Codex CLI, Claude CLI, and OpenCode remain usable.",
            "acceptance_criteria": ["Gemini absence must not block the workflow."],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _authorizations(plan):
        return {effect.plan_id: authorize(effect) for effect in plan.effect_plans}

    def _prepare_and_apply(self):
        plan = prepare_research_run(
            REPO_ROOT, self.store, self.ownership, self.prepare_request,
        )
        result = apply_research_run(
            plan,
            self._authorizations(plan),
            expected_plan_id=plan.plan_id,
        )
        self.assertEqual("applied", result["status"])
        return plan

    def test_prepare_creates_five_provider_independent_prompt_packets(self) -> None:
        plan = self._prepare_and_apply()
        self.assertEqual(8, len(plan.documents))
        self.assertFalse(plan.public_summary()["gemini_required"])
        self.assertEqual(
            "optional-provider-unavailable",
            plan.public_summary()["optional_provider_statuses"]["gemini"],
        )
        for role in (
            "researcher", "architecture-reviewer", "critic", "synthesizer",
            "citation-verifier",
        ):
            prompt = plan.root / "prompts" / f"{role}.md"
            self.assertTrue(prompt.is_file())
            self.assertIn("untrusted data", prompt.read_text(encoding="utf-8"))
        repeated = prepare_research_run(
            REPO_ROOT, self.store, self.ownership, self.prepare_request,
        )
        self.assertTrue(repeated.no_op)

    def test_objective_only_request_uses_portable_title_fallback(self) -> None:
        request = {
            "schema_ref": "schemas/research-run-request.schema.json",
            "schema_version": 1,
            "research_id": "objective-only",
            "scope": "global",
            "objective": "Evaluate the provider-independent workflow.",
        }
        plan = prepare_research_run(
            REPO_ROOT, self.store, self.ownership, request,
        )
        request_document = plan.documents[plan.root / "request.md"].decode("utf-8")
        self.assertTrue(request_document.startswith("# objective-only"))
        self.assertIn("Evaluate the provider-independent workflow.", request_document)

    def test_question_or_objective_is_required_and_empty_values_fail(self) -> None:
        missing = {
            "schema_ref": "schemas/research-run-request.schema.json",
            "schema_version": 1,
            "research_id": "missing-objective",
            "scope": "global",
        }
        with self.assertRaisesRegex(ResearchOrchestrationError, "question or objective"):
            prepare_research_run(REPO_ROOT, self.store, self.ownership, missing)
        empty = dict(missing, objective="Valid objective", question="   ")
        with self.assertRaisesRegex(ResearchOrchestrationError, "question"):
            prepare_research_run(REPO_ROOT, self.store, self.ownership, empty)
        schema = json.loads(
            (REPO_ROOT / "schemas" / "research-run-request.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)
        objective_only = {
            **missing,
            "research_id": "schema-objective-only",
            "objective": "Valid objective",
        }
        self.assertEqual([], list(validator.iter_errors(objective_only)))
        self.assertTrue(list(validator.iter_errors(missing)))
        self.assertTrue(list(validator.iter_errors(empty)))

    def test_import_contract_requires_all_typed_fields(self) -> None:
        self._prepare_and_apply()
        incomplete = {
            "schema_ref": "schemas/research-result-import-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "role": "researcher",
            "provider": "manual",
            "model": "declared-unverified",
            "response_markdown": "# Result",
        }
        with self.assertRaisesRegex(ResearchOrchestrationError, "fields"):
            prepare_research_result_import(
                REPO_ROOT, self.store, self.ownership, incomplete,
            )

    def test_import_is_untrusted_revisioned_and_idempotent(self) -> None:
        plan = self._prepare_and_apply()
        request = {
            "schema_ref": "schemas/research-result-import-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "role": "researcher",
            "provider": "gemini-web",
            "model": "declared-unverified",
            "response_markdown": "# Findings\n\nGemini remains optional.",
            "findings": {
                "sources": [{"source_id": "source-1", "url": "https://example.invalid/research"}],
                "claims": [{"claim_id": "claim-1", "source_ids": ["source-1"]}],
                "conflicts": [],
            },
        }
        import_plan = prepare_research_result_import(
            REPO_ROOT, self.store, self.ownership, request,
        )
        result = apply_research_result_import(
            import_plan,
            self._authorizations(import_plan),
            expected_plan_id=import_plan.plan_id,
        )
        self.assertEqual("untrusted", result["trust"])
        self.assertFalse(result["knowledge_promoted"])
        repeated = prepare_research_result_import(
            REPO_ROOT, self.store, self.ownership, request,
        )
        self.assertTrue(repeated.no_op)
        status = get_research_status(
            self.store, {"research_id": "provider-options", "scope": "global"},
        )
        self.assertEqual(1, status["response_count"])
        self.assertEqual("optional-provider-unavailable", status["optional_provider_statuses"]["gemini"])
        self.assertNotIn(str(self.home), str(status))
        self.assertNotIn("gemini-web", str(status))
        for private_field in ("provider", "model", "client_id", "execution_target"):
            self.assertNotIn(private_field, status["responses"][0])
        self.assertTrue((plan.root / "raw" / "researcher-r1.md").is_file())

    def test_same_raw_with_changed_metadata_creates_revision_and_conflict(self) -> None:
        plan = self._prepare_and_apply()
        request = {
            "schema_ref": "schemas/research-result-import-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "role": "researcher",
            "provider": "manual-a",
            "model": "model-a",
            "client_id": "codex",
            "execution_target": "operator-handoff",
            "response_markdown": "# Same raw response",
            "findings": {"sources": [], "claims": [], "conflicts": []},
        }
        first = prepare_research_result_import(
            REPO_ROOT, self.store, self.ownership, request,
        )
        apply_research_result_import(
            first, self._authorizations(first), expected_plan_id=first.plan_id,
        )
        changed = dict(request)
        changed["provider"] = "manual-b"
        changed["model"] = "model-b"
        changed["findings"] = {
            "sources": [{"source_id": "source-2"}],
            "claims": [{"claim_id": "claim-2", "source_ids": ["source-2"]}],
            "conflicts": [],
        }
        second = prepare_research_result_import(
            REPO_ROOT, self.store, self.ownership, changed,
        )
        self.assertFalse(second.no_op)
        self.assertEqual(2, second.revision)
        apply_research_result_import(
            second, self._authorizations(second), expected_plan_id=second.plan_id,
        )
        repeated = prepare_research_result_import(
            REPO_ROOT, self.store, self.ownership, changed,
        )
        self.assertTrue(repeated.no_op)
        structured = json.loads(
            (plan.root / "findings" / "researcher-r2.json").read_text(encoding="utf-8")
        )
        self.assertEqual([1], structured["same_raw_prior_revisions"])
        self.assertEqual("same-raw-different-metadata", structured["conflicts"][0]["kind"])
        status = get_research_status(
            self.store, {"research_id": "provider-options", "scope": "global"},
        )
        self.assertEqual(2, status["response_count"])
        self.assertNotIn("manual-b", str(status))
        self.assertNotIn("model-b", str(status))

    def _import_one_response(self) -> Path:
        plan = self._prepare_and_apply()
        request = {
            "schema_ref": "schemas/research-result-import-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "role": "researcher",
            "provider": "manual",
            "model": "declared-unverified",
            "response_markdown": "# Verified before tamper",
            "findings": {"sources": [], "claims": [], "conflicts": []},
        }
        imported = prepare_research_result_import(
            REPO_ROOT, self.store, self.ownership, request,
        )
        apply_research_result_import(
            imported, self._authorizations(imported), expected_plan_id=imported.plan_id,
        )
        return plan.root

    def test_status_rejects_tampered_artifact_reference(self) -> None:
        root = self._import_one_response()
        manifest_path = root / "_krcn" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["responses"][0]["artifact_ref"] = "../outside.md"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ResearchOrchestrationError, "portable"):
            get_research_status(
                self.store, {"research_id": "provider-options", "scope": "global"},
            )

    def test_status_rejects_manifest_secret_and_raw_tamper(self) -> None:
        root = self._import_one_response()
        manifest_path = root / "_krcn" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["responses"][0]["provider"] = (
            "github_" + "pat_abcdefghijklmnopqrstuvwxyz1234567890"
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ResearchOrchestrationError, "github-token"):
            get_research_status(
                self.store, {"research_id": "provider-options", "scope": "global"},
            )
        manifest["responses"][0]["provider"] = "manual"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (root / "raw" / "researcher-r1.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ResearchOrchestrationError, "raw response digest"):
            get_research_status(
                self.store, {"research_id": "provider-options", "scope": "global"},
            )

    def test_exact_plan_and_fail_closed_input_are_enforced(self) -> None:
        plan = prepare_research_run(
            REPO_ROOT, self.store, self.ownership, self.prepare_request,
        )
        with self.assertRaisesRegex(ResearchOrchestrationError, "exact plan"):
            apply_research_run(
                plan, self._authorizations(plan), expected_plan_id="0" * 64,
            )
        invalid = dict(self.prepare_request, unexpected=True)
        with self.assertRaisesRegex(ResearchOrchestrationError, "fields"):
            prepare_research_run(REPO_ROOT, self.store, self.ownership, invalid)

    def test_secret_and_machine_path_are_rejected(self) -> None:
        secret = dict(
            self.prepare_request,
            question="Use token github_" + "pat_abcdefghijklmnopqrstuvwxyz1234567890",
        )
        with self.assertRaisesRegex(ResearchOrchestrationError, "github-token"):
            prepare_research_run(REPO_ROOT, self.store, self.ownership, secret)
        absolute = dict(self.prepare_request, context="Read C:" + "\\private\\source")
        with self.assertRaisesRegex(ResearchOrchestrationError, "windows-absolute-path"):
            prepare_research_run(REPO_ROOT, self.store, self.ownership, absolute)

    def _create_directory_link(self, link: Path, target: Path, *, junction: bool) -> None:
        target.mkdir(parents=True, exist_ok=True)
        if junction:
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest("Windows junction creation is unavailable")
            return
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")

    @staticmethod
    def _remove_directory_link(link: Path) -> None:
        if not link.exists() and not link.is_symlink():
            return
        if os.name == "nt" and getattr(link, "is_junction", lambda: False)():
            os.rmdir(link)
        else:
            link.unlink()

    def _assert_ancestor_escape_is_rejected(self, *, junction: bool) -> None:
        plan = prepare_research_run(
            REPO_ROOT, self.store, self.ownership, self.prepare_request,
        )
        outside = self.home.parent / ("junction-outside" if junction else "symlink-outside")
        link = self.home / "global"
        self._create_directory_link(link, outside, junction=junction)
        try:
            with self.assertRaisesRegex(
                ResearchOrchestrationError,
                "symlink or junction",
            ):
                apply_research_run(
                    plan,
                    self._authorizations(plan),
                    expected_plan_id=plan.plan_id,
                )
            self.assertEqual([], list(outside.rglob("manifest.json")))
            with self.assertRaisesRegex(
                ResearchOrchestrationError,
                "symlink or junction",
            ):
                prepare_research_run(
                    REPO_ROOT, self.store, self.ownership, self.prepare_request,
                )
        finally:
            self._remove_directory_link(link)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_junction_ancestor_escape_after_plan_is_rejected(self) -> None:
        self._assert_ancestor_escape_is_rejected(junction=True)

    def test_symlink_ancestor_escape_after_plan_is_rejected(self) -> None:
        self._assert_ancestor_escape_is_rejected(junction=False)


if __name__ == "__main__":
    unittest.main()

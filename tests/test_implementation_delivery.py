from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from krcn_core.foundation import load_json
from krcn_core.implementation_delivery import (
    ImplementationDeliveryError,
    apply_implementation_plan,
    prepare_implementation_plan,
    verify_implementation_result,
)
from krcn_core.mutation_gate import DryRunEvidence, OwnershipResolver, authorize_mutation
from krcn_core.worktree_sandbox import (
    build_sandbox_host_profile,
    collect_patch_artifact,
    create_detached_worktree,
    prepare_worktree_sandbox,
    remove_detached_worktree,
)


ROOT = Path(__file__).resolve().parents[1]
SHA = hashlib.sha256(b"phase-27").hexdigest()


class PassingRunner:
    def __init__(self, passed: bool = True): self.passed = passed
    def run(self, repo_root: Path, test_id: str, command_digest: str):
        return {"passed": self.passed, "evidence_digest": hashlib.sha256((test_id + command_digest).encode()).hexdigest()}


class ImplementationDeliveryTests(unittest.TestCase):
    def test_plan_apply_verify_and_schema_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); repo = self.repo(base / "repo")
            sandbox_plan, artifact, sandbox = self.artifact(repo, base)
            try:
                plan = self.plan(repo, artifact)
                before = subprocess.check_output(["git", "-C", str(repo), "diff"])
                self.assertEqual(b"", before)
                auths = {item.plan_id: authorize_mutation(item, dry_run=DryRunEvidence(item.plan_id, True)) for item in plan.mutation_plans}
                result = apply_implementation_plan(plan, artifact, auths, expected_plan_id=plan.plan_id, current_report_bytes=b"reviewed report", test_runner=PassingRunner())
                self.assertIn(b"changed", (repo / "src" / "module.py").read_bytes())
                verification = verify_implementation_result(plan, result, verifier_identity_digest=SHA, verifier_evidence_digest=SHA)
                self.assertTrue(verification.payload["completion_allowed"])
                for name, value in (("implementation-plan", plan.as_dict()), ("implementation-result", result.as_dict()), ("implementation-verification", verification.as_dict())):
                    schema = load_json(ROOT / "schemas" / f"{name}.schema.json")
                    self.assertEqual([], list(Draft202012Validator(schema).iter_errors(value)))
            finally:
                remove_detached_worktree(sandbox_plan, sandbox)

    def test_stale_report_missing_authority_and_failed_test_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); repo = self.repo(base / "repo")
            sandbox_plan, artifact, sandbox = self.artifact(repo, base)
            try:
                plan = self.plan(repo, artifact)
                with self.assertRaisesRegex(ImplementationDeliveryError, "report changed"):
                    apply_implementation_plan(plan, artifact, {}, expected_plan_id=plan.plan_id, current_report_bytes=b"different", test_runner=PassingRunner())
                with self.assertRaisesRegex(ImplementationDeliveryError, "authorization"):
                    apply_implementation_plan(plan, artifact, {}, expected_plan_id=plan.plan_id, current_report_bytes=b"reviewed report", test_runner=PassingRunner())
                auths = {item.plan_id: authorize_mutation(item, dry_run=DryRunEvidence(item.plan_id, True)) for item in plan.mutation_plans}
                with self.assertRaisesRegex(ImplementationDeliveryError, "test failed"):
                    apply_implementation_plan(plan, artifact, auths, expected_plan_id=plan.plan_id, current_report_bytes=b"reviewed report", test_runner=PassingRunner(False))
                self.assertEqual("print('base')\n", (repo / "src" / "module.py").read_text())
            finally:
                remove_detached_worktree(sandbox_plan, sandbox)

    def plan(self, repo: Path, artifact):
        return prepare_implementation_plan(repo, OwnershipResolver.from_repository(ROOT), project_id="fixture-project", work_item_id="implementation-work", task_plan_id=SHA, report_ref="research/report.md", report_bytes=b"reviewed report", artifact=artifact, test_specs=({"test_id": "unit", "command_digest": SHA},), execution_trace_ref="traces/phase-27")

    def artifact(self, repo: Path, base: Path):
        host = build_sandbox_host_profile(host_id="test-host", os_family="windows", detached_worktree=True, path_isolation=True, environment_allowlist=True, network_default_deny=True, commit_push_blocked=True, junction_guard=True)
        plan = prepare_worktree_sandbox(repo, OwnershipResolver.from_repository(ROOT), project_id="fixture-project", task_plan_id=SHA, worker_step_id="implementation", validation_gate_id=SHA, effect_claim_id=SHA, allowed_paths=("src",), allowed_executables=("python",), allowed_env_keys=(), host_profile=host)
        auth = authorize_mutation(plan.mutation_plan, dry_run=DryRunEvidence(plan.mutation_plan.plan_id, True))
        sandbox = create_detached_worktree(plan, auth, sandbox_parent=base / "sandboxes")
        (sandbox / "src" / "module.py").write_text("print('changed')\n", encoding="utf-8")
        return plan, collect_patch_artifact(plan, sandbox, effect_receipt_id=SHA, verifier_evidence_digest=SHA), sandbox

    @staticmethod
    def repo(path: Path) -> Path:
        (path / "src").mkdir(parents=True); (path / "src" / "module.py").write_text("print('base')\n")
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        fixture_mail = "test" + "@" + "example.invalid"
        subprocess.run(["git", "-C", str(path), "-c", "user.name=Test", "-c", f"user.email={fixture_mail}", "commit", "-q", "-m", "base"], check=True)
        return path


if __name__ == "__main__": unittest.main()

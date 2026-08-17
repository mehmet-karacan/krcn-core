from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from krcn_core.foundation import load_json
from krcn_core.mutation_gate import DryRunEvidence, OwnershipResolver, authorize_mutation
from krcn_core.worktree_sandbox import (
    WorktreeSandboxError,
    build_sandbox_host_profile,
    collect_patch_artifact,
    create_detached_worktree,
    prepare_worktree_sandbox,
    parse_sandbox_patch_artifact,
    remove_detached_worktree,
)


ROOT = Path(__file__).resolve().parents[1]
SHA = hashlib.sha256(b"binding").hexdigest()


class WorktreeSandboxTests(unittest.TestCase):
    def host(self, os_family: str = "windows", **overrides: bool):
        values = {
            "detached_worktree": True,
            "path_isolation": True,
            "environment_allowlist": True,
            "network_default_deny": True,
            "commit_push_blocked": True,
            "junction_guard": True,
        }
        values.update(overrides)
        return build_sandbox_host_profile(host_id=f"{os_family}-host", os_family=os_family, **values)

    def plan(self, repo: Path, host=None, allowed_paths=("src",)):
        return prepare_worktree_sandbox(
            repo, OwnershipResolver.from_repository(ROOT), project_id="fixture-project",
            task_plan_id=SHA, worker_step_id="implementation", validation_gate_id=SHA,
            effect_claim_id=SHA, allowed_paths=allowed_paths,
            allowed_executables=("python",), allowed_env_keys=("PYTHONPATH",),
            host_profile=host or self.host(),
        )

    def test_windows_and_linux_profiles_require_all_enforcement(self) -> None:
        for family in ("windows", "linux"):
            with self.subTest(family=family):
                profile = self.host(family)
                self.assertTrue(profile.execution_allowed)
                schema = load_json(ROOT / "schemas" / "sandbox-host-profile.schema.json")
                self.assertEqual([], list(Draft202012Validator(schema).iter_errors(profile.as_dict())))
        self.assertFalse(self.host("windows", network_default_deny=False).execution_allowed)

    def test_traversal_absolute_windows_unc_and_case_collision_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = self._repo(Path(raw))
            bad = ("../escape", "/outside", "D:" + "/outside", "//host/share")
            for path in bad:
                with self.subTest(path=path), self.assertRaises(WorktreeSandboxError):
                    self.plan(repo, allowed_paths=(path,))
            with self.assertRaisesRegex(WorktreeSandboxError, "case-colliding"):
                self.plan(repo, allowed_paths=("src/File.py", "src/file.py"))

    def test_real_detached_worktree_collects_only_allowlisted_patch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = self._repo(base / "repo")
            plan = self.plan(repo)
            plan_schema = load_json(ROOT / "schemas" / "worktree-sandbox-plan.schema.json")
            self.assertEqual([], list(Draft202012Validator(plan_schema).iter_errors(plan.as_dict())))
            auth = authorize_mutation(plan.mutation_plan, dry_run=DryRunEvidence(plan.mutation_plan.plan_id, True))
            sandbox = create_detached_worktree(plan, auth, sandbox_parent=base / "sandboxes")
            try:
                target = sandbox / "src" / "module.py"
                target.write_text("print('changed')\n", encoding="utf-8")
                artifact = collect_patch_artifact(
                    plan, sandbox, effect_receipt_id=SHA, verifier_evidence_digest=SHA,
                )
                self.assertEqual(["src/module.py"], [item["path_ref"] for item in artifact.payload["changed_files"]])
                self.assertTrue(artifact.patch_bytes)
                self.assertFalse(artifact.payload["contains_patch_bytes"])
                parse_sandbox_patch_artifact(artifact.as_dict())
                schema = load_json(ROOT / "schemas" / "sandbox-patch-artifact.schema.json")
                self.assertEqual([], list(Draft202012Validator(schema).iter_errors(artifact.as_dict())))
            finally:
                remove_detached_worktree(plan, sandbox)

    def test_outside_allowlist_and_commit_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = self._repo(base / "repo")
            plan = self.plan(repo)
            auth = authorize_mutation(plan.mutation_plan, dry_run=DryRunEvidence(plan.mutation_plan.plan_id, True))
            sandbox = create_detached_worktree(plan, auth, sandbox_parent=base / "sandboxes")
            try:
                (sandbox / "README.md").write_text("changed\n", encoding="utf-8")
                with self.assertRaisesRegex(WorktreeSandboxError, "outside"):
                    collect_patch_artifact(plan, sandbox, effect_receipt_id=SHA, verifier_evidence_digest=SHA)
                subprocess.run(["git", "-C", str(sandbox), "add", "README.md"], check=True, stdout=subprocess.PIPE)
                fixture_mail = "test" + "@" + "example.invalid"
                subprocess.run(["git", "-C", str(sandbox), "-c", "user.name=Test", "-c", f"user.email={fixture_mail}", "commit", "-m", "test"], check=True, stdout=subprocess.PIPE)
                with self.assertRaisesRegex(WorktreeSandboxError, "commit drift"):
                    collect_patch_artifact(plan, sandbox, effect_receipt_id=SHA, verifier_evidence_digest=SHA)
            finally:
                remove_detached_worktree(plan, sandbox)

    def test_stale_source_and_insufficient_host_block_before_create(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = self._repo(base / "repo")
            blocked = self.plan(repo, host=self.host(network_default_deny=False))
            auth = authorize_mutation(blocked.mutation_plan, dry_run=DryRunEvidence(blocked.mutation_plan.plan_id, True))
            with self.assertRaisesRegex(WorktreeSandboxError, "insufficient"):
                create_detached_worktree(blocked, auth, sandbox_parent=base / "sandboxes")
            plan = self.plan(repo)
            (repo / "src" / "module.py").write_text("next\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            fixture_mail = "test" + "@" + "example.invalid"
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", f"user.email={fixture_mail}", "commit", "-m", "next"], check=True, stdout=subprocess.PIPE)
            auth = authorize_mutation(plan.mutation_plan, dry_run=DryRunEvidence(plan.mutation_plan.plan_id, True))
            with self.assertRaisesRegex(WorktreeSandboxError, "stale"):
                create_detached_worktree(plan, auth, sandbox_parent=base / "sandboxes")

    def test_untracked_patch_is_included_and_output_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = self._repo(base / "repo")
            plan = prepare_worktree_sandbox(
                repo, OwnershipResolver.from_repository(ROOT), project_id="fixture-project",
                task_plan_id=SHA, worker_step_id="implementation", validation_gate_id=SHA,
                effect_claim_id=SHA, allowed_paths=("src",), allowed_executables=("python",),
                allowed_env_keys=(), host_profile=self.host(), maximum_patch_bytes=8,
            )
            auth = authorize_mutation(plan.mutation_plan, dry_run=DryRunEvidence(plan.mutation_plan.plan_id, True))
            sandbox = create_detached_worktree(plan, auth, sandbox_parent=base / "sandboxes")
            try:
                (sandbox / "src" / "new.py").write_text("content\n", encoding="utf-8")
                with self.assertRaisesRegex(WorktreeSandboxError, "bounded output"):
                    collect_patch_artifact(plan, sandbox, effect_receipt_id=SHA, verifier_evidence_digest=SHA)
            finally:
                remove_detached_worktree(plan, sandbox)

    @staticmethod
    def _repo(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        (path / "src").mkdir()
        (path / "src" / "module.py").write_text("print('base')\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        fixture_mail = "test" + "@" + "example.invalid"
        subprocess.run(["git", "-C", str(path), "-c", "user.name=Test", "-c", f"user.email={fixture_mail}", "commit", "-q", "-m", "base"], check=True)
        return path


if __name__ == "__main__":
    unittest.main()

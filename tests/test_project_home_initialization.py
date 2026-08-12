from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_home import (  # noqa: E402
    choose_project_home,
    resolve_project_home,
    select_project_home_parent,
)
from krcn_core.project_home_initialization import (  # noqa: E402
    MANIFEST_NAME,
    ProjectHomeInitializationError,
    apply_project_home_initialization,
    prepare_project_home_initialization,
)


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


class ProjectHomeInitializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ownership = OwnershipResolver.from_repository(REPO_ROOT)

    def selected_default(self, project: Path):
        proposal = resolve_project_home(project, environ={})
        selected = choose_project_home(proposal, "use-default")
        assert selected is not None
        return selected

    def authorizations(self, plan):
        result = {}
        for mutation in plan.effect_plans:
            result[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, True),
                approval=ApprovalEvidence(
                    mutation.plan_id,
                    "project-home-approval",
                    True,
                ),
            )
        return result

    def initialize_git_repository(self, root: Path) -> None:
        result = git(root, "init", "--quiet")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_repository_contract_classifies_and_excludes_project_home(self) -> None:
        ownership = json.loads(
            (REPO_ROOT / "config" / "ownership-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        user_data = next(
            item for item in ownership["classes"] if item["id"] == "user-data"
        )
        self.assertIn(".krcn/project-home.json", user_data["paths"])
        self.assertIn(".krcn/local-data/**", user_data["paths"])
        imports = json.loads(
            (REPO_ROOT / "config" / "import-policy.json").read_text(encoding="utf-8")
        )
        self.assertIn("**/.krcn/**", imports["blocked_globs"])

    def test_unselected_default_cannot_prepare_a_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposal = resolve_project_home(Path(directory), environ={})
            with self.assertRaisesRegex(
                ProjectHomeInitializationError,
                "explicit user choice",
            ):
                prepare_project_home_initialization(proposal, self.ownership)
            self.assertFalse((Path(directory) / ".krcn").exists())

    def test_non_git_project_requires_exact_authorization_and_writes_only_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = self.selected_default(project)
            with patch(
                "krcn_core.project_home_initialization._git_root",
                return_value=None,
            ):
                plan = prepare_project_home_initialization(selected, self.ownership)
            self.assertEqual(1, len(plan.effect_plans))
            self.assertEqual("user-data", plan.effect_plans[0].ownership)
            self.assertFalse(selected.path.exists())
            with self.assertRaisesRegex(
                ProjectHomeInitializationError,
                "matching authorization",
            ):
                with patch(
                    "krcn_core.project_home_initialization._git_root",
                    return_value=None,
                ):
                    apply_project_home_initialization(plan, {}, self.ownership)
            with patch(
                "krcn_core.project_home_initialization._git_root",
                return_value=None,
            ):
                result = apply_project_home_initialization(
                    plan,
                    self.authorizations(plan),
                    self.ownership,
                )
            self.assertTrue(result.home_created)
            self.assertFalse(result.git_exclusion_updated)
            self.assertEqual([MANIFEST_NAME], [item.name for item in selected.path.iterdir()])
            payload = json.loads(
                (selected.path / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertFalse(payload["source_copy"])
            self.assertFalse(payload["local_data_in_git"])
            self.assertNotIn(str(project), str(payload))

    def test_git_project_uses_local_exclude_without_changing_tracked_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_git_repository(project)
            tracked_ignore = project / ".gitignore"
            tracked_ignore.write_text("build/\n", encoding="utf-8")
            selected = self.selected_default(project)
            plan = prepare_project_home_initialization(selected, self.ownership)
            self.assertIsNotNone(plan.git_exclusion)
            self.assertEqual(2, len(plan.effect_plans))
            public = plan.public_summary()
            local = plan.public_summary(disclose_path=True)
            self.assertFalse(public["git_exclusion"]["path_disclosed"])
            self.assertNotIn("ignore_pattern", public["git_exclusion"])
            self.assertTrue(local["git_exclusion"]["path_disclosed"])
            self.assertEqual("/.krcn/", local["git_exclusion"]["ignore_pattern"])
            result = apply_project_home_initialization(
                plan,
                self.authorizations(plan),
                self.ownership,
            )
            self.assertTrue(result.home_created)
            self.assertTrue(result.git_exclusion_updated)
            self.assertEqual("build/\n", tracked_ignore.read_text(encoding="utf-8"))
            exclude = project / ".git" / "info" / "exclude"
            self.assertIn("/.krcn/", exclude.read_text(encoding="utf-8"))
            ignored = git(
                project,
                "check-ignore",
                "--no-index",
                "-q",
                "--",
                f".krcn/{MANIFEST_NAME}",
            )
            self.assertEqual(0, ignored.returncode)
            status = git(project, "status", "--short")
            self.assertNotIn(".krcn", status.stdout)

    def test_existing_repository_ignore_needs_no_local_exclude_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_git_repository(project)
            (project / ".gitignore").write_text("/.krcn/\n", encoding="utf-8")
            selected = self.selected_default(project)
            plan = prepare_project_home_initialization(selected, self.ownership)
            self.assertIsNone(plan.git_exclusion)
            self.assertEqual(1, len(plan.effect_plans))

    def test_custom_home_outside_project_does_not_change_project_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            selected_parent = root / "data"
            project.mkdir()
            selected_parent.mkdir()
            self.initialize_git_repository(project)
            selected = select_project_home_parent(project, selected_parent)
            exclude = project / ".git" / "info" / "exclude"
            before = exclude.read_bytes()
            plan = prepare_project_home_initialization(selected, self.ownership)
            self.assertIsNone(plan.git_exclusion)
            apply_project_home_initialization(
                plan,
                self.authorizations(plan),
                self.ownership,
            )
            self.assertEqual(before, exclude.read_bytes())
            self.assertTrue((selected.path / MANIFEST_NAME).is_file())

    def test_ambiguous_existing_target_is_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            home = project / ".krcn"
            home.mkdir()
            (home / "unknown.txt").write_text("user data", encoding="utf-8")
            selected = self.selected_default(project)
            with self.assertRaisesRegex(
                ProjectHomeInitializationError,
                "not an initialized KRCN home",
            ):
                prepare_project_home_initialization(selected, self.ownership)
            self.assertEqual("user data", (home / "unknown.txt").read_text(encoding="utf-8"))

    def test_tracked_project_home_is_rejected_without_untracking_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_git_repository(project)
            home = project / ".krcn"
            home.mkdir()
            tracked = home / "tracked.txt"
            tracked.write_text("preserve", encoding="utf-8")
            added = git(project, "add", "-f", ".krcn/tracked.txt")
            self.assertEqual(0, added.returncode, added.stderr)
            selected = self.selected_default(project)
            with self.assertRaises(ProjectHomeInitializationError):
                prepare_project_home_initialization(selected, self.ownership)
            self.assertEqual("preserve", tracked.read_text(encoding="utf-8"))
            self.assertIn(".krcn/tracked.txt", git(project, "ls-files").stdout)

    def test_applied_plan_is_idempotently_inspected_without_new_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = self.selected_default(project)
            first = prepare_project_home_initialization(selected, self.ownership)
            apply_project_home_initialization(
                first,
                self.authorizations(first),
                self.ownership,
            )
            second = prepare_project_home_initialization(selected, self.ownership)
            self.assertTrue(second.already_initialized)
            self.assertEqual((), second.effect_plans)
            result = apply_project_home_initialization(second, {}, self.ownership)
            self.assertFalse(result.home_created)
            self.assertFalse(result.git_exclusion_updated)

    def test_changed_git_exclude_makes_the_plan_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_git_repository(project)
            selected = self.selected_default(project)
            plan = prepare_project_home_initialization(selected, self.ownership)
            assert plan.git_exclusion is not None
            with plan.git_exclusion.exclude_path.open("ab") as stream:
                stream.write(b"/other-local-data/\n")
            with self.assertRaisesRegex(
                ProjectHomeInitializationError,
                "plan changed",
            ):
                apply_project_home_initialization(
                    plan,
                    self.authorizations(plan),
                    self.ownership,
                )
            self.assertFalse(selected.path.exists())


if __name__ == "__main__":
    unittest.main()

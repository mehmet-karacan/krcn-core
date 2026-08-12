from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.project_home import (  # noqa: E402
    ProjectHomeError,
    resolve_project_home,
    select_project_home_parent,
)


class ProjectHomeResolutionTests(unittest.TestCase):
    def test_project_default_is_a_non_mutating_choice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = resolve_project_home(project, environ={})
            self.assertEqual((project / ".krcn").resolve(), result.path)
            self.assertEqual("project-default", result.source)
            self.assertEqual("choice-required", result.status)
            self.assertTrue(result.requires_user_choice)
            self.assertTrue(result.requires_initialization)
            self.assertFalse(result.path.exists())
            self.assertEqual(
                ("use-default", "choose-parent", "cancel"), result.choices
            )

    def test_explicit_exact_path_has_highest_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            explicit = root / "exact-home"
            result = resolve_project_home(
                project,
                explicit_data_root=explicit,
                remembered_home=root / "remembered",
                environ={"KRCN_HOME": str(root / "environment")},
            )
            self.assertEqual(explicit.resolve(), result.path)
            self.assertEqual("explicit", result.source)
            self.assertFalse(result.requires_user_choice)
            self.assertEqual("custom", result.target_kind)

    def test_environment_precedes_remembered_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            configured = root / "environment-home"
            result = resolve_project_home(
                project,
                remembered_home=root / "remembered",
                environ={"KRCN_HOME": str(configured)},
            )
            self.assertEqual(configured.resolve(), result.path)
            self.assertEqual("environment", result.source)

    def test_remembered_selection_precedes_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            remembered = root / "remembered"
            result = resolve_project_home(
                project,
                remembered_home=remembered,
                environ={},
            )
            self.assertEqual(remembered.resolve(), result.path)
            self.assertEqual("remembered", result.source)
            self.assertFalse(result.requires_user_choice)

    def test_user_selected_parent_gets_one_krcn_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            selected = root / "selected"
            project.mkdir()
            selected.mkdir()
            result = select_project_home_parent(project, selected)
            self.assertEqual((selected / ".krcn").resolve(), result.path)
            self.assertEqual("user-selected", result.source)
            self.assertIn("custom-home-outside-project", result.warnings)
            self.assertFalse(result.path.exists())

    def test_public_summary_redacts_path_until_local_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = resolve_project_home(project, environ={})
            public = result.as_dict()
            local = result.as_dict(disclose_path=True)
            self.assertFalse(public["path_disclosed"])
            self.assertNotIn("target_path", public)
            self.assertTrue(local["path_disclosed"])
            self.assertEqual(str(result.path), local["target_path"])

    def test_existing_selected_home_is_reported_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            result = resolve_project_home(
                project,
                explicit_data_root=home,
                environ={},
            )
            self.assertEqual("selected-existing", result.status)
            self.assertFalse(result.requires_initialization)

    def test_relative_and_missing_project_roots_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectHomeError, "absolute path"):
            resolve_project_home(Path("relative"), environ={})
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with self.assertRaisesRegex(ProjectHomeError, "must exist"):
                resolve_project_home(missing, environ={})

    def test_symbolic_link_target_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            target = root / "target"
            link = root / "link"
            project.mkdir()
            target.mkdir()
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable")
            with self.assertRaisesRegex(ProjectHomeError, "symbolic link"):
                resolve_project_home(
                    project,
                    explicit_data_root=link,
                    environ={},
                )


if __name__ == "__main__":
    unittest.main()

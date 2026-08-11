from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.policies import evaluate_policies, load_user_policies  # noqa: E402
from krcn_core.project_metadata import ProjectMetadataError  # noqa: E402


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


class PhaseSevenIntegrationTests(unittest.TestCase):
    def test_prompt_only_onboarding_preserves_source_and_existing_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "müşteri uygulaması"
            source.mkdir()
            unique_source_text = "yalnız-dış-projede-kalması-gereken-içerik"
            (source / "package.json").write_text(
                '{"name":"müşteri-uygulaması"}\n',
                encoding="utf-8",
            )
            (source / "src").mkdir()
            (source / "src" / "app.js").write_text(
                unique_source_text,
                encoding="utf-8",
            )
            user_home = root / "krcn-home"
            policies = user_home / "policies"
            policies.mkdir(parents=True)
            policy_payload = {
                "schema_version": 1,
                "policy_id": "database-select-only",
                "scope": {"kind": "global", "ref": None},
                "revision": 1,
                "rules": [
                    {
                        "rule_id": "deny-delete",
                        "resource_type": "database",
                        "operations": ["delete"],
                        "effect": "deny",
                        "constraints": {"allowed_operations": ["select"]},
                        "provenance": {"kind": "explicit-user"},
                        "active": True,
                    }
                ],
            }
            policy_path = policies / "database-select-only.json"
            policy_path.write_text(
                json.dumps(policy_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            policy_before = policy_path.read_bytes()
            source_before = snapshot(source)
            service = create_application_service(REPO_ROOT, user_home)
            arguments = {
                "request_text": f'"{source}" projesini öğren ve entegre et'
            }
            dry_run = service.execute(
                ServiceRequest("codex", "project.learn", arguments)
            )
            plan = dry_run.data["plan"]
            self.assertEqual("planned", dry_run.status)
            self.assertEqual("musteri-uygulamasi", plan["metadata"]["project_id"])
            self.assertEqual(4, len(plan["record_plans"]))
            self.assertFalse(plan["source_copy"])
            self.assertNotIn(str(source), json.dumps(plan, ensure_ascii=False))
            applied = service.execute(
                ServiceRequest(
                    "codex",
                    "project.learn",
                    arguments,
                    apply=True,
                    expected_plan_id=plan["plan_id"],
                    approval_id="phase-seven-single-approval",
                )
            )
            self.assertEqual("applied", applied.status)
            store = LocalWorkspaceStore(
                user_home,
                OwnershipResolver.from_repository(REPO_ROOT),
            )
            for record_type, record_id in (
                ("projects", "musteri-uygulamasi"),
                ("workspaces", "musteri-uygulamasi-workspace"),
                ("source-bindings", "musteri-uygulamasi-local"),
                ("source-states", "musteri-uygulamasi-local"),
            ):
                self.assertIsNotNone(store.read(record_type, record_id))
            self.assertEqual(source_before, snapshot(source))
            self.assertEqual(policy_before, policy_path.read_bytes())
            persisted_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in user_home.rglob("*.json")
            )
            self.assertNotIn(unique_source_text, persisted_text)
            self.assertFalse(any(path.name == "app.js" for path in user_home.rglob("*")))
            decision = evaluate_policies(
                load_user_policies(policies),
                resource_type="database",
                operation="delete",
                scope_refs={"project": "musteri-uygulamasi"},
            )
            self.assertEqual("deny", decision.effect)
            with self.assertRaisesRegex(ProjectMetadataError, "already registered"):
                service.execute(ServiceRequest("plugin", "project.learn", arguments))


if __name__ == "__main__":
    unittest.main()

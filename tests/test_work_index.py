from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_graph import build_work_item, parse_work_item  # noqa: E402
from krcn_core.work_index import (  # noqa: E402
    WorkIndexError,
    apply_work_index,
    load_work_index_policy,
    prepare_work_index,
    render_work_index,
    work_index_path,
)


def schema_registry() -> Registry:
    registry = Registry()
    for path in (REPO_ROOT / "schemas").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema_id = payload.get("$id")
        if isinstance(schema_id, str):
            registry = registry.with_resource(schema_id, Resource.from_contents(payload))
        registry = registry.with_resource(path.name, Resource.from_contents(payload))
    return registry


class WorkIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "sample",
            "name": "Sample",
            "description": "Readable work index test project",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        plan = self.store.prepare_put(
            "projects", "sample", project, expected_revision=0, project_id="sample"
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id, "test-approval", approved=True
            ),
        )
        self.store.apply_put(plan, authorization)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def item(
        work_item_id: str,
        *,
        status: str = "active",
        title: str | None = None,
        description: str = "Private description must not enter the index",
        revision: int = 1,
    ):
        evidence = []
        if status == "completed":
            evidence = [{
                "evidence_type": "file",
                "reference": "work-documents/private/file.sql",
                "digest": "a" * 64,
                "label": "Private evidence label",
            }]
        return build_work_item({
            "work_item_id": work_item_id,
            "project_id": "sample",
            "work_type": "task",
            "title": title or f"Task {work_item_id}",
            "description": description,
            "status": status,
            "acceptance_criteria": ["Private acceptance detail"],
            "relations": [],
            "evidence": evidence,
            "provenance": {
                "source_kind": "user",
                "source_ref": "private-source-ref",
            },
        }, revision)

    def put_item(self, item) -> None:
        current = self.store.read("work-items", item.work_item_id)
        plan = self.store.prepare_put(
            "work-items",
            item.work_item_id,
            item.as_dict(),
            expected_revision=0 if current is None else current.revision,
            project_id="sample",
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id, "test-approval", approved=True
            ),
        )
        self.store.apply_put(plan, authorization)

    def authorize_index(self, plan):
        assert plan.mutation is not None
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )

    def test_render_is_deterministic_safe_and_readable(self) -> None:
        policy = load_work_index_policy(REPO_ROOT)
        private_path = "C:" + "/Us" + "ers/example/private"
        secret_assignment = "to" + "ken=" + "abcdefgh12345678"
        active = self.item(
            "task-active",
            title=(
                f"Fix {private_path} and /etc/passwd "
                f"{secret_assignment} | now"
            ),
        )
        done = self.item("task-done", status="completed")
        first = render_work_index("sample", (done, active), "b" * 64, policy)
        second = render_work_index("sample", (active, done), "b" * 64, policy)
        self.assertEqual(first.document, second.document)
        text = first.document.decode("utf-8")
        self.assertIn("## Active work", text)
        self.assertIn("## Historical work", text)
        self.assertIn("task-active", text)
        self.assertIn("[redacted-path]", text)
        self.assertIn("[redacted-secret]", text)
        self.assertNotIn("Private description", text)
        self.assertNotIn("work-documents/private", text)
        self.assertNotIn("private-source-ref", text)
        self.assertNotIn("abcdefgh12345678", text)
        self.assertNotIn("/etc/passwd", text)

    def test_active_items_are_mandatory_and_history_is_bounded(self) -> None:
        policy = replace(load_work_index_policy(REPO_ROOT), maximum_items=2)
        active = self.item("task-active")
        history = tuple(
            self.item(f"task-done-{index}", status="completed")
            for index in range(3)
        )
        result = render_work_index("sample", (active, *history), "c" * 64, policy)
        self.assertEqual(1, result.active_item_count)
        self.assertEqual(3, result.historical_item_count)
        self.assertEqual(2, result.listed_item_count)
        self.assertEqual(2, result.omitted_item_count)
        with self.assertRaises(WorkIndexError):
            render_work_index(
                "sample",
                (active, self.item("task-active-two")),
                "d" * 64,
                replace(policy, maximum_items=1),
            )
        byte_policy = replace(
            load_work_index_policy(REPO_ROOT),
            maximum_document_bytes=4096,
        )
        many_history = tuple(
            self.item(
                f"task-large-{index}",
                status="completed",
                title=("Historical bounded title " + str(index) + " ") * 12,
            )
            for index in range(40)
        )
        bounded = render_work_index(
            "sample", (active, *many_history), "e" * 64, byte_policy
        )
        self.assertLessEqual(len(bounded.document), 4096)
        self.assertGreater(bounded.omitted_item_count, 0)
        self.assertIn("task-active", bounded.document.decode("utf-8"))

    def test_exact_plan_apply_stale_rejection_and_no_op(self) -> None:
        self.put_item(self.item("task-one"))
        plan = prepare_work_index(REPO_ROOT, self.store, self.ownership, "sample")
        self.assertFalse(plan.no_op)
        result = apply_work_index(
            REPO_ROOT,
            self.store,
            self.ownership,
            plan,
            self.authorize_index(plan),
            expected_plan_id=plan.plan_id,
        )
        self.assertEqual("applied", result["status"])
        target = work_index_path(self.home, "sample")
        self.assertTrue(target.is_file())
        current = prepare_work_index(REPO_ROOT, self.store, self.ownership, "sample")
        self.assertTrue(current.no_op)
        current_result = apply_work_index(
            REPO_ROOT,
            self.store,
            self.ownership,
            current,
            None,
            expected_plan_id=current.plan_id,
        )
        self.assertEqual("current", current_result["status"])

        stale = current
        self.put_item(self.item("task-two"))
        with self.assertRaises(WorkIndexError):
            apply_work_index(
                REPO_ROOT,
                self.store,
                self.ownership,
                stale,
                None,
                expected_plan_id=stale.plan_id,
            )

    def test_public_contracts_match_json_schemas(self) -> None:
        self.put_item(self.item("task-schema"))
        plan = prepare_work_index(REPO_ROOT, self.store, self.ownership, "sample")
        result = apply_work_index(
            REPO_ROOT,
            self.store,
            self.ownership,
            plan,
            self.authorize_index(plan),
            expected_plan_id=plan.plan_id,
        )
        registry = schema_registry()
        for name, payload in (
            ("work-index-plan.schema.json", plan.public_summary()),
            ("work-index-result.schema.json", result),
        ):
            schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            errors = list(Draft202012Validator(schema, registry=registry).iter_errors(payload))
            self.assertEqual([], errors)

    def test_application_and_cli_rebuild_a_missing_readable_index(self) -> None:
        self.put_item(self.item("task-cli"))
        service = create_application_service(REPO_ROOT, self.home)
        planned = service.execute(ServiceRequest(
            "codex",
            "work.index-readable",
            {"project_id": "sample"},
        ))
        self.assertEqual("planned", planned.status)
        applied = service.execute(ServiceRequest(
            "codex",
            "work.index-readable",
            {"project_id": "sample"},
            apply=True,
            expected_plan_id=str(planned.data["plan"]["plan_id"]),
        ))
        self.assertEqual("applied", applied.status)
        self.assertTrue(work_index_path(self.home, "sample").is_file())

        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            exit_code = main([
                "work",
                "index-readable",
                "sample",
                "--repo",
                str(REPO_ROOT),
                "--data-root",
                str(self.home),
            ])
        self.assertEqual(0, exit_code, error.getvalue())
        self.assertIn("Proje: sample", output.getvalue())
        self.assertIn("Aktif: 1", output.getvalue())
        self.assertNotIn(str(self.home), output.getvalue())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is unavailable")
    def test_link_like_target_is_rejected_when_platform_allows_creation(self) -> None:
        self.put_item(self.item("task-link"))
        target = work_index_path(self.home, "sample")
        target.parent.mkdir(parents=True)
        outside = Path(self.temporary.name) / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest("link creation is not permitted in this environment")
        with self.assertRaises(WorkIndexError):
            prepare_work_index(REPO_ROOT, self.store, self.ownership, "sample")

    def test_stored_work_items_parse_before_projection(self) -> None:
        item = self.item("task-parse")
        self.put_item(item)
        stored = self.store.read("work-items", item.work_item_id)
        self.assertEqual(item.work_digest, parse_work_item(stored.payload).work_digest)


if __name__ == "__main__":
    unittest.main()

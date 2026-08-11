from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.derived_actions import (  # noqa: E402
    DerivedActionError,
    DerivedActionHandler,
    DerivedActionHandlerRegistry,
    plan_derived_writes,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.update_effects import DerivedActionSpec  # noqa: E402


class DerivedActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.scope = self.root / ".krcn" / "derived" / "catalog"
        self.scope.mkdir(parents=True)
        (self.scope / "keep.json").write_text(
            '{"value":1}\n',
            encoding="utf-8",
        )
        (self.scope / "remove.json").write_text(
            '{"obsolete":true}\n',
            encoding="utf-8",
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.spec = DerivedActionSpec(
            "rebuild-catalog",
            ".krcn/derived/catalog",
            "rebuild",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _rebuild(_payload):
        return {
            "keep.json": {"value": 2},
            "nested/new.json": {"created": True},
        }

    def test_plans_exact_create_update_and_delete_writes(self) -> None:
        handlers = DerivedActionHandlerRegistry(
            [DerivedActionHandler("rebuild-catalog", self._rebuild)]
        )
        writes = plan_derived_writes(
            self.root,
            (self.spec,),
            handlers,
            self.ownership,
        )
        actions = {item.target_ref: item.action for item in writes}
        self.assertEqual(
            {
                ".krcn/derived/catalog/keep.json": "update",
                ".krcn/derived/catalog/nested/new.json": "create",
                ".krcn/derived/catalog/remove.json": "delete",
            },
            actions,
        )
        self.assertTrue(all(item.mutation.reversible for item in writes))
        self.assertTrue(actions)

    def test_non_idempotent_handler_is_rejected(self) -> None:
        def increment(payload):
            current = payload.get("keep.json", {"value": 0})
            return {"keep.json": {"value": current["value"] + 1}}

        handlers = DerivedActionHandlerRegistry(
            [DerivedActionHandler("rebuild-catalog", increment)]
        )
        with self.assertRaisesRegex(DerivedActionError, "idempotent"):
            plan_derived_writes(
                self.root,
                (self.spec,),
                handlers,
                self.ownership,
            )

    def test_handler_cannot_write_outside_json_scope(self) -> None:
        handlers = DerivedActionHandlerRegistry(
            [
                DerivedActionHandler(
                    "rebuild-catalog",
                    lambda _payload: {"../escape.json": {}},
                )
            ]
        )
        with self.assertRaisesRegex(DerivedActionError, "stay in JSON scope"):
            plan_derived_writes(
                self.root,
                (self.spec,),
                handlers,
                self.ownership,
            )

    def test_invalid_source_json_is_rejected(self) -> None:
        (self.scope / "keep.json").write_text("{", encoding="utf-8")
        handlers = DerivedActionHandlerRegistry(
            [DerivedActionHandler("rebuild-catalog", self._rebuild)]
        )
        with self.assertRaisesRegex(DerivedActionError, "input JSON"):
            plan_derived_writes(
                self.root,
                (self.spec,),
                handlers,
                self.ownership,
            )


if __name__ == "__main__":
    unittest.main()

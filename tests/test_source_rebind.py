from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.adapter_gate import (  # noqa: E402
    authorize_adapter_operation,
    prepare_adapter_operation,
)
from krcn_core.discovery import (  # noqa: E402
    LOCAL_DISCOVERY_ADAPTER,
    discover_local_source,
    load_discovery_policy,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.source_bindings import parse_source_binding  # noqa: E402
from krcn_core.source_rebind import (  # noqa: E402
    SourceRebindError,
    apply_source_rebind,
    candidate_binding,
    classify_source_relocation,
    prepare_source_rebind,
)
from krcn_core.source_identity import SourceIdentity  # noqa: E402
from krcn_core.source_state import source_state_from_discovery  # noqa: E402


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return result


class SourceRebindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.old_source = root / "old-project"
        self.new_source = root / "restored-project"
        self.user_home = root / "krcn-home"
        for source in (self.old_source, self.new_source):
            (source / "src").mkdir(parents=True)
            (source / "src" / "main.py").write_text(
                "print('portable')\n",
                encoding="utf-8",
            )
            (source / "pyproject.toml").write_text(
                "[project]\nname='portable'\n",
                encoding="utf-8",
            )
        self.store = LocalWorkspaceStore(
            self.user_home,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.binding = parse_source_binding(
            {
                "schema_version": 1,
                "binding_id": "portable-project-local",
                "source_id": "portable-project",
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(self.old_source)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            }
        )
        self._put(
            "source-bindings",
            self.binding.binding_id,
            {
                "schema_version": 1,
                "binding_id": self.binding.binding_id,
                "source_id": self.binding.source_id,
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(self.old_source)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            },
        )
        discovery = self._discover(self.binding)
        self._put(
            "source-states",
            self.binding.binding_id,
            source_state_from_discovery(discovery).as_payload(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put(self, record_type: str, record_id: str, payload: dict) -> None:
        plan = self.store.prepare_put(record_type, record_id, payload, expected_revision=0)
        approval = None
        if plan.mutation.approval_required:
            approval = ApprovalEvidence(plan.mutation.plan_id, "setup-approval", True)
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=approval,
        )
        self.store.apply_put(plan, authorization)

    @staticmethod
    def _authorizations(plan):
        result = {}
        for record_plan in plan.record_plans:
            mutation = record_plan.mutation
            approval = None
            if mutation.approval_required:
                approval = ApprovalEvidence(mutation.plan_id, "rebind-approval", True)
            result[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, True),
                approval=approval,
            )
        return result

    @staticmethod
    def _discover(binding):
        request = prepare_adapter_operation(
            LOCAL_DISCOVERY_ADAPTER,
            binding,
            "discover",
            [],
        )
        return discover_local_source(
            binding,
            load_discovery_policy(REPO_ROOT),
            authorize_adapter_operation(request),
        )

    def test_exact_rebind_changes_only_local_records(self) -> None:
        candidate = candidate_binding(self.binding, self.new_source)
        before_old = snapshot(self.old_source)
        before_new = snapshot(self.new_source)
        discovery = self._discover(candidate)
        plan = prepare_source_rebind(
            self.store,
            self.binding,
            self.new_source,
            discovery,
        )
        self.assertTrue(plan.public_summary()["identity_verified"])
        self.assertEqual("relocated-same-source", plan.public_summary()["classification"])
        self.assertEqual(
            "verify-current-manifest-and-reuse",
            plan.public_summary()["index_action"],
        )
        self.assertNotIn(str(self.new_source), json.dumps(plan.public_summary()))
        schema = json.loads(
            (REPO_ROOT / "schemas" / "source-rebind-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [],
            list(Draft202012Validator(schema).iter_errors(plan.public_summary())),
        )
        result = apply_source_rebind(
            self.store,
            plan,
            self._authorizations(plan),
            candidate,
            discovery,
        )
        rebound = self.store.read("source-bindings", self.binding.binding_id)
        state = self.store.read("source-states", self.binding.binding_id)
        self.assertEqual(str(self.new_source.resolve()), rebound.payload["locator"]["value"])
        self.assertEqual(2, rebound.payload["revision"])
        self.assertEqual(2, state.payload["binding_revision"])
        self.assertFalse(result.public_summary()["source_mutated"])
        self.assertEqual(
            "relocated-same-source", result.public_summary()["classification"]
        )
        self.assertEqual(before_old, snapshot(self.old_source))
        self.assertEqual(before_new, snapshot(self.new_source))
        self.assertFalse((self.user_home / "restored-project").exists())

    def test_rebind_stops_when_candidate_content_does_not_match(self) -> None:
        (self.new_source / "src" / "main.py").write_text(
            "print('different')\n",
            encoding="utf-8",
        )
        candidate = candidate_binding(self.binding, self.new_source)
        with self.assertRaisesRegex(SourceRebindError, "Git relationship evidence"):
            prepare_source_rebind(
                self.store,
                self.binding,
                self.new_source,
                self._discover(candidate),
            )

    def test_apply_requires_matching_exact_plan_authorizations(self) -> None:
        candidate = candidate_binding(self.binding, self.new_source)
        discovery = self._discover(candidate)
        plan = prepare_source_rebind(
            self.store,
            self.binding,
            self.new_source,
            discovery,
        )
        with self.assertRaisesRegex(SourceRebindError, "every rebind write"):
            apply_source_rebind(self.store, plan, {}, candidate, discovery)

    def test_rebind_rejects_the_already_active_locator(self) -> None:
        with self.assertRaisesRegex(SourceRebindError, "already the active binding"):
            prepare_source_rebind(
                self.store,
                self.binding,
                self.old_source,
                self._discover(self.binding),
            )


class SourceRelocationClassificationTests(unittest.TestCase):
    @staticmethod
    def identity(
        *,
        source_id: str = "portable-project",
        binding_id: str = "portable-project-local",
        digest: str = "a" * 64,
        file_count: int = 2,
    ) -> SourceIdentity:
        return SourceIdentity(
            source_id,
            binding_id,
            "krcn-discovery-tree-sha256-v1",
            digest,
            file_count,
        )

    def test_same_digest_is_locator_only_and_schema_valid(self) -> None:
        assessment = classify_source_relocation(self.identity(), self.identity())
        payload = assessment.public_summary()

        self.assertEqual("relocated-same-source", assessment.classification)
        self.assertTrue(assessment.rebind_allowed)
        self.assertFalse(assessment.integration_required)
        self.assertFalse(assessment.reconciliation_required)
        schema = json.loads(
            (
                REPO_ROOT
                / "schemas"
                / "source-relocation-assessment.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [],
            list(Draft202012Validator(schema).iter_errors(payload)),
        )

    def test_linear_diverged_and_unrelated_candidates_have_distinct_actions(self) -> None:
        expected = self.identity()
        changed = self.identity(digest="b" * 64)
        linear = classify_source_relocation(
            expected, changed, revision_relation="linear-history"
        )
        diverged = classify_source_relocation(
            expected, changed, revision_relation="diverged-history"
        )
        unrelated = classify_source_relocation(
            expected, changed, revision_relation="unrelated-history"
        )

        self.assertEqual("same-project-new-revision", linear.classification)
        self.assertTrue(linear.integration_required)
        self.assertEqual("mark-stale-and-rebuild", linear.index_action)
        self.assertEqual("diverged-clone", diverged.classification)
        self.assertTrue(diverged.reconciliation_required)
        self.assertEqual("separate-revision-index", diverged.index_action)
        self.assertEqual("unrelated-source", unrelated.classification)
        self.assertEqual("create-separate-project", unrelated.index_action)
        self.assertFalse(any(item.rebind_allowed for item in (linear, diverged, unrelated)))

    def test_logical_identity_mismatch_is_unrelated_even_with_same_digest(self) -> None:
        assessment = classify_source_relocation(
            self.identity(),
            self.identity(source_id="another-project"),
        )
        self.assertEqual("unrelated-source", assessment.classification)
        self.assertFalse(assessment.rebind_allowed)

    def test_changed_content_without_reviewed_history_evidence_fails_closed(self) -> None:
        with self.assertRaisesRegex(SourceRebindError, "evidence is required"):
            classify_source_relocation(
                self.identity(),
                self.identity(digest="b" * 64),
            )


if __name__ == "__main__":
    unittest.main()

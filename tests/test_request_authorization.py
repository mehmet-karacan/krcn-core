from __future__ import annotations

import tempfile
import unittest
import sys
import time
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import KrcnApplicationService, ServiceRequest
from krcn_core.home_layout import user_home_layout_bytes
from krcn_core.local_store import LocalWorkspaceStore
from krcn_core.mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationGateError,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)
from krcn_core.request_authorization import (
    RequestAuthorizationError,
    authorize_explicit_local_request,
    mint_initiating_request_evidence,
)
from krcn_core.work_graph import apply_work_item, prepare_work_item
from krcn_core.cli import app as cli_app


class RequestAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name)
        (self.data_root / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.data_root, self.ownership)
        project = self.store.prepare_put(
            "projects",
            "sample",
            {
                "schema_version": 1,
                "project_id": "sample",
                "name": "Sample",
                "description": "Request authorization fixture",
                "status": "active",
                "source_refs": [],
                "modules": [],
                "technologies": [],
                "skill_refs": [],
            },
            expected_revision=0,
            project_id="sample",
        )
        self.store.apply_put(
            project,
            authorize_mutation(
                project.mutation,
                dry_run=DryRunEvidence(project.mutation.plan_id, True),
                approval=ApprovalEvidence(project.mutation.plan_id, "fixture", True),
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _work_arguments(
        title: str = "Authorized task",
        work_item_id: str = "authorized-task",
    ) -> dict[str, object]:
        return {
            "work_item_id": work_item_id,
            "project_id": "sample",
            "work_type": "task",
            "title": title,
            "description": "One exact local mutation",
            "status": "active",
            "acceptance_criteria": ["The exact task record exists"],
            "relations": [],
            "evidence": [],
            "provenance": {"source_kind": "user", "source_ref": "current-turn"},
        }

    def test_trusted_exact_request_applies_once_and_replays_prior_result(self) -> None:
        evidence_by_request = {}

        def trusted_host(request: ServiceRequest):
            if request.intent_request_id not in evidence_by_request:
                evidence_by_request[request.intent_request_id] = (
                    mint_initiating_request_evidence(
                        session_id="codex-session-1",
                        intent_request_id=request.intent_request_id,
                        user_turn_digest="a" * 64,
                        source="trusted-host",
                        lifetime_seconds=2,
                    ).as_dict()
                )
            return evidence_by_request[request.intent_request_id]

        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            trusted_request_evidence_provider=trusted_host,
        )
        planned = service.execute(
            ServiceRequest("codex", "work.item.put", self._work_arguments())
        )
        plan_id = planned.data["plan"]["plan_id"]
        request = ServiceRequest(
            "codex", "work.item.put", self._work_arguments(),
            apply=True, expected_plan_id=plan_id,
        )
        first = service.execute(request)
        repeated = service.execute(request)
        restarted_service = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(self.data_root, self.ownership),
            trusted_request_evidence_provider=trusted_host,
        )
        process_independent_replay = restarted_service.execute(request)
        self.assertEqual("applied", first.status)
        self.assertEqual(first.as_dict(), repeated.as_dict())
        self.assertEqual(first.as_dict(), process_independent_replay.as_dict())
        self.assertEqual("consumed", first.data["authorization_receipt"]["status"])
        self.assertEqual(1, self.store.read("work-items", "authorized-task").revision)
        def transferred_host(current: ServiceRequest):
            return mint_initiating_request_evidence(
                session_id="another-session",
                intent_request_id=current.intent_request_id,
                user_turn_digest="a" * 64,
                source="trusted-host",
            ).as_dict()

        transferred_service = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(self.data_root, self.ownership),
            trusted_request_evidence_provider=transferred_host,
        )
        with self.assertRaisesRegex(ValueError, "cannot be transferred"):
            transferred_service.execute(request)
        time.sleep(2.1)
        with self.assertRaisesRegex(ValueError, "expired"):
            service.execute(request)

    def test_request_scope_swap_and_cli_self_assertion_fail_closed(self) -> None:
        plan = plan_mutation(
            self.ownership,
            operation="create",
            target_ref=".krcn/projects/sample/work/items/authorized-task.json",
            expected_ownership="user-data",
            change_digest="b" * 64,
            reversible=True,
        )
        base = ServiceRequest(
            "codex", "work.item.put", self._work_arguments(),
            apply=True, expected_plan_id=plan.plan_id,
        )
        evidence = mint_initiating_request_evidence(
            session_id="codex-session-2",
            intent_request_id=base.intent_request_id,
            user_turn_digest="c" * 64,
            source="trusted-host",
        )
        authorization = authorize_explicit_local_request(
            evidence=evidence,
            intent_request_id=base.intent_request_id,
            operation=base.operation,
            plan_id=plan.plan_id,
            project_id="sample",
            effects=(plan,),
        )
        swapped = plan_mutation(
            self.ownership,
            operation="create",
            target_ref=".krcn/projects/sample/work/items/swapped-task.json",
            expected_ownership="user-data",
            change_digest="d" * 64,
            reversible=True,
        )
        with self.assertRaisesRegex(MutationGateError, "approval"):
            authorize_mutation(
                swapped,
                dry_run=DryRunEvidence(swapped.plan_id, True),
            )
        self.assertFalse(authorization.permits(swapped))
        cli_request = ServiceRequest(
            "cli", "work.item.put", self._work_arguments(),
            apply=True, expected_plan_id=plan.plan_id,
        )
        self.assertFalse(hasattr(cli_request, "initiating_request"))

    def test_stale_unknown_destructive_and_cross_project_requests_stay_gated(self) -> None:
        plan = plan_mutation(
            self.ownership,
            operation="create",
            target_ref=".krcn/projects/sample/work/items/authorized-task.json",
            expected_ownership="user-data",
            change_digest="e" * 64,
            reversible=True,
        )
        now = datetime.now(timezone.utc)
        stale = mint_initiating_request_evidence(
            session_id="codex-session-3",
            intent_request_id="f" * 64,
            user_turn_digest="1" * 64,
            source="trusted-host",
            now=now - timedelta(minutes=2),
            lifetime_seconds=1,
        )
        with self.assertRaisesRegex(RequestAuthorizationError, "stale"):
            authorize_explicit_local_request(
                evidence=stale,
                intent_request_id="f" * 64,
                operation="work.item.put",
                plan_id=plan.plan_id,
                project_id="sample",
                effects=(plan,),
                now=now,
            )
        fresh = mint_initiating_request_evidence(
            session_id="codex-session-4",
            intent_request_id="2" * 64,
            user_turn_digest="3" * 64,
            source="trusted-host",
            now=now,
        )
        with self.assertRaisesRegex(RequestAuthorizationError, "outside the reviewed"):
            authorize_explicit_local_request(
                evidence=fresh,
                intent_request_id="2" * 64,
                operation="implementation.apply",
                plan_id=plan.plan_id,
                project_id="sample",
                effects=(plan,),
                now=now,
            )
        other = plan_mutation(
            self.ownership,
            operation="create",
            target_ref=".krcn/projects/other/work/items/other-task.json",
            expected_ownership="user-data",
            change_digest="4" * 64,
            reversible=True,
        )
        with self.assertRaisesRegex(RequestAuthorizationError, "cross-project"):
            authorize_explicit_local_request(
                evidence=fresh,
                intent_request_id="2" * 64,
                operation="work.item.put",
                plan_id=plan.plan_id,
                project_id=None,
                effects=(plan, other),
                now=now,
            )
        with self.assertRaisesRegex(RequestAuthorizationError, "dangerous-action"):
            authorize_explicit_local_request(
                evidence=fresh,
                intent_request_id="2" * 64,
                operation="database.oracle.collect",
                plan_id=plan.plan_id,
                project_id="sample",
                effects=(plan,),
                now=now,
            )
        deletion = plan_mutation(
            self.ownership,
            operation="delete",
            target_ref=".krcn/projects/sample/work/items/authorized-task.json",
            expected_ownership="user-data",
            change_digest="5" * 64,
            reversible=True,
        )
        with self.assertRaisesRegex(RequestAuthorizationError, "destructive"):
            authorize_explicit_local_request(
                evidence=fresh,
                intent_request_id="2" * 64,
                operation="work.item.put",
                plan_id=deletion.plan_id,
                project_id="sample",
                effects=(deletion,),
                now=now,
            )

    def test_only_human_owned_interactive_cli_boundary_mints_cli_evidence(self) -> None:
        request = ServiceRequest(
            "cli", "work.item.put", self._work_arguments(),
            apply=True, expected_plan_id="5" * 64,
        )

        class Terminal:
            @staticmethod
            def isatty():
                return True

        class Pipe:
            @staticmethod
            def isatty():
                return False

        with patch.object(cli_app.sys, "stdin", Terminal()), patch.object(
            cli_app.sys, "argv", ["krcn", "ask", "gorevi guncelle"]
        ):
            evidence = cli_app._interactive_cli_evidence(request)
        self.assertEqual("typed-cli", evidence["source"])
        self.assertEqual(request.intent_request_id, evidence["intent_request_id"])
        with patch.object(cli_app.sys, "stdin", Pipe()):
            self.assertIsNone(cli_app._interactive_cli_evidence(request))

    def test_trusted_host_boundary_is_client_neutral(self) -> None:
        evidence_by_request = {}

        def trusted_host(request: ServiceRequest):
            evidence_by_request.setdefault(
                request.intent_request_id,
                mint_initiating_request_evidence(
                    session_id=f"{request.client_kind}-session",
                    intent_request_id=request.intent_request_id,
                    user_turn_digest="6" * 64,
                    source="trusted-host",
                ).as_dict(),
            )
            return evidence_by_request[request.intent_request_id]

        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            trusted_request_evidence_provider=trusted_host,
        )
        for client in ("codex", "claude", "opencode"):
            arguments = self._work_arguments(
                title=f"{client} authorized task",
                work_item_id=f"{client}-authorized-task",
            )
            planned = service.execute(
                ServiceRequest(client, "work.item.put", arguments)
            )
            applied = service.execute(
                ServiceRequest(
                    client,
                    "work.item.put",
                    arguments,
                    apply=True,
                    expected_plan_id=planned.data["plan"]["plan_id"],
                )
            )
            self.assertEqual("consumed", applied.data["authorization_receipt"]["status"])

    def test_terminal_receipt_failure_leaves_durable_non_reexecuting_recovery(self) -> None:
        evidence_by_request = {}

        def trusted_host(request: ServiceRequest):
            evidence_by_request.setdefault(
                request.intent_request_id,
                mint_initiating_request_evidence(
                    session_id="fault-session",
                    intent_request_id=request.intent_request_id,
                    user_turn_digest="b" * 64,
                    source="trusted-host",
                ).as_dict(),
            )
            return evidence_by_request[request.intent_request_id]

        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            trusted_request_evidence_provider=trusted_host,
        )
        arguments = self._work_arguments(work_item_id="fault-task")
        planned = service.execute(ServiceRequest("codex", "work.item.put", arguments))
        request = ServiceRequest(
            "codex", "work.item.put", arguments,
            apply=True, expected_plan_id=planned.data["plan"]["plan_id"],
        )
        with patch.object(
            service,
            "_persist_authorization_receipt",
            side_effect=OSError("injected receipt failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected receipt"):
                service.execute(request)
        self.assertEqual(1, self.store.read("work-items", "fault-task").revision)
        restarted = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(self.data_root, self.ownership),
            trusted_request_evidence_provider=trusted_host,
        )
        recovered = restarted.execute(request)
        self.assertEqual("applied", recovered.status)
        self.assertTrue(recovered.data["reconciled"])
        self.assertFalse(recovered.data["effects_reexecuted"])
        self.assertFalse(recovered.data["approval_required"])
        self.assertEqual(1, self.store.read("work-items", "fault-task").revision)

    def test_partial_apply_returns_machine_readable_local_repair_action(self) -> None:
        evidence_by_request = {}

        def trusted_host(request: ServiceRequest):
            evidence_by_request.setdefault(
                request.intent_request_id,
                mint_initiating_request_evidence(
                    session_id="partial-session",
                    intent_request_id=request.intent_request_id,
                    user_turn_digest="c" * 64,
                    source="trusted-host",
                ).as_dict(),
            )
            return evidence_by_request[request.intent_request_id]

        service = KrcnApplicationService(
            REPO_ROOT, self.store,
            trusted_request_evidence_provider=trusted_host,
        )
        arguments = self._work_arguments(work_item_id="partial-task")
        planned = service.execute(ServiceRequest("codex", "work.item.put", arguments))
        request = ServiceRequest(
            "codex", "work.item.put", arguments,
            apply=True, expected_plan_id=planned.data["plan"]["plan_id"],
        )
        original_apply = self.store.apply_put

        def interrupt_after_item(write, authorization):
            if write.record_type == "work-events":
                raise OSError("injected partial apply")
            return original_apply(write, authorization)

        with patch.object(self.store, "apply_put", side_effect=interrupt_after_item):
            with self.assertRaisesRegex(OSError, "partial apply"):
                service.execute(request)
        restarted = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(self.data_root, self.ownership),
            trusted_request_evidence_provider=trusted_host,
        )
        recovery = restarted.execute(request)
        self.assertEqual("recovery-required", recovery.status)
        self.assertEqual(
            "request.authorization.repair-local",
            recovery.data["next_operation"],
        )
        self.assertFalse(recovery.data["approval_required"])

    def test_pending_claim_with_no_started_effect_executes_once_on_retry(self) -> None:
        evidence_by_request = {}

        def trusted_host(request: ServiceRequest):
            evidence_by_request.setdefault(
                request.intent_request_id,
                mint_initiating_request_evidence(
                    session_id="not-started-session",
                    intent_request_id=request.intent_request_id,
                    user_turn_digest="d" * 64,
                    source="trusted-host",
                ).as_dict(),
            )
            return evidence_by_request[request.intent_request_id]

        service = KrcnApplicationService(
            REPO_ROOT, self.store,
            trusted_request_evidence_provider=trusted_host,
        )
        arguments = self._work_arguments(work_item_id="not-started-task")
        planned = service.execute(ServiceRequest("codex", "work.item.put", arguments))
        request = ServiceRequest(
            "codex", "work.item.put", arguments,
            apply=True, expected_plan_id=planned.data["plan"]["plan_id"],
        )
        original_apply = self.store.apply_put

        def interrupt_first_effect(write, authorization):
            if write.record_type == "work-items":
                raise OSError("injected before first effect")
            return original_apply(write, authorization)

        with patch.object(self.store, "apply_put", side_effect=interrupt_first_effect):
            with self.assertRaisesRegex(OSError, "before first effect"):
                service.execute(request)
        self.assertIsNone(self.store.read("work-items", "not-started-task"))
        restarted = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(self.data_root, self.ownership),
            trusted_request_evidence_provider=trusted_host,
        )
        applied = restarted.execute(request)
        self.assertEqual("applied", applied.status)
        self.assertEqual(1, self.store.read("work-items", "not-started-task").revision)

    def test_routine_derived_effect_needs_no_approval_but_persistent_source_does(self) -> None:
        service = KrcnApplicationService(REPO_ROOT, self.store)
        derived = plan_mutation(
            self.ownership,
            operation="create",
            target_ref=".krcn/projects/sample/derived/retrieval/test.sqlite",
            expected_ownership="derived",
            change_digest="7" * 64,
            reversible=True,
        )
        routine = ServiceRequest(
            "codex", "work.index-semantic", {"project_id": "sample"},
            apply=True, expected_plan_id=derived.plan_id,
        )
        authorizations = service._authorize_effect_plans(
            routine, derived.plan_id, (derived,), "derived repair"
        )
        self.assertTrue(authorizations[derived.plan_id].dry_run_verified)
        source = plan_mutation(
            self.ownership,
            operation="update",
            target_ref="src/krcn_core/application.py",
            expected_ownership="core",
            change_digest="8" * 64,
            reversible=True,
        )
        implementation = ServiceRequest(
            "codex", "implementation.apply", {},
            apply=True, expected_plan_id=source.plan_id,
        )
        with self.assertRaisesRegex(ValueError, "approval id"):
            service._authorize_effect_plans(
                implementation,
                source.plan_id,
                (source,),
                "implementation delivery",
            )

    def test_explicit_ask_same_request_applies_for_all_client_ids(self) -> None:
        for index, client in enumerate(("codex", "claude", "opencode"), start=1):
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(REPO_ROOT / "src")
            environment["KRCN_CLIENT_ID"] = client
            environment["KRCN_SESSION_ID"] = f"{client}-subprocess-session"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "krcn_core.cli.app",
                    "ask",
                    f"sample için ASK-{index} görevi oluştur",
                    "--apply",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.data_root),
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            response = json.loads(completed.stdout)
            self.assertEqual("applied", response["status"])
            self.assertEqual(
                "consumed",
                response["data"]["authorization_receipt"]["status"],
            )
            fresh = self.store.read("work-items", f"sample-task-ask-{index}")
            self.assertIsNotNone(fresh)
            self.assertEqual(1, fresh.revision)
            self.assertIsNotNone(
                self.store.read("work-events", f"sample-task-ask-{index}-r1")
            )

        rich_arguments = {
            "work_item_id": "sample-task-rich-duplicate",
            "project_id": "sample",
            "work_type": "task",
            "title": "Rich existing task",
            "description": "These rich fields must never be overwritten by create intent.",
            "status": "proposed",
            "acceptance_criteria": [
                "Preserve every existing field",
                "Do not append an event for a rejected duplicate create",
            ],
            "relations": [],
            "evidence": [{
                "evidence_type": "document",
                "reference": "fixture:rich-existing",
                "digest": "e" * 64,
                "label": "Rich duplicate-create regression fixture",
            }],
            "provenance": {
                "source_kind": "user",
                "source_ref": "fixture:rich-existing",
            },
        }
        rich_plan = prepare_work_item(
            self.store,
            self.ownership,
            rich_arguments,
            repo_root=REPO_ROOT,
        )
        apply_work_item(
            self.store,
            rich_plan,
            {
                effect.plan_id: authorize_mutation(
                    effect,
                    dry_run=DryRunEvidence(effect.plan_id, True),
                    approval=(
                        ApprovalEvidence(effect.plan_id, "fixture", True)
                        if effect.approval_required
                        else None
                    ),
                )
                for effect in rich_plan.effect_plans
            },
        )
        original = self.store.read("work-items", "sample-task-rich-duplicate")
        self.assertEqual(1, original.revision)

        def collection_snapshot(collection: str):
            return [
                (record.record_id, record.revision, record.payload)
                for record in self.store.list_records(collection)
            ]

        events_before = collection_snapshot("work-events")
        receipts_before = collection_snapshot("request-authorization-receipts")
        conflicting_environment = dict(os.environ)
        conflicting_environment["PYTHONPATH"] = str(REPO_ROOT / "src")
        conflicting_environment["KRCN_CLIENT_ID"] = "codex"
        conflicting_environment["KRCN_SESSION_ID"] = "new-codex-session"
        conflict = subprocess.run(
            [
                sys.executable,
                "-m",
                "krcn_core.cli.app",
                "ask",
                "sample için RICH-DUPLICATE görevi oluştur",
                "--apply",
                "--repo",
                str(REPO_ROOT),
                "--data-root",
                str(self.data_root),
                "--format",
                "json",
            ],
            cwd=REPO_ROOT,
            env=conflicting_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(2, conflict.returncode)
        after = self.store.read("work-items", "sample-task-rich-duplicate")
        self.assertEqual(original.payload, after.payload)
        self.assertEqual(1, after.revision)
        self.assertEqual(events_before, collection_snapshot("work-events"))
        self.assertEqual(
            receipts_before,
            collection_snapshot("request-authorization-receipts"),
        )


if __name__ == "__main__":
    unittest.main()

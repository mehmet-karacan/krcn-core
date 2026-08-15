from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    MutationGateError,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.information_records import canonical_json  # noqa: E402
from krcn_core.skill_lifecycle import (  # noqa: E402
    SkillLifecycleError,
    build_skill_candidate,
    build_skill_evaluation,
    finalize_skill_registry_change,
    find_skill_candidate_duplicates,
    load_skill_lifecycle_policy,
    parse_skill_candidate,
    parse_skill_evaluation,
    parse_skill_lifecycle_record,
    parse_skill_registry_change_plan,
    prepare_skill_activation,
    prepare_skill_state_change,
)


class SkillLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_skill_lifecycle_policy(REPO_ROOT)
        self.resolver = OwnershipResolver.from_repository(REPO_ROOT)

    @staticmethod
    def candidate(candidate_id: str = "context-candidate", source: str = "a"):
        return build_skill_candidate(
            candidate_id=candidate_id,
            skill_id="context-curator",
            proposed_by_ref=f"actor:{candidate_id}",
            proposer_identity_digest="4" * 64,
            source_refs=["research:report-one", "work:repeat-one"],
            source_digest=source * 64,
            repetition_digests=["b" * 64, "c" * 64],
            proposer_model_digest="d" * 64,
        )

    def evaluation(self, candidate=None, *, trials: int = 3, passed: int = 3, score: int = 9500):
        candidate = candidate or self.candidate()
        return build_skill_evaluation(
            self.policy,
            candidate,
            evaluation_id="context-evaluation",
            project_fixture_digest="e" * 64,
            evaluation_run_digest="f" * 64,
            evaluator_ref="actor:evaluator",
            verifier_ref="actor:verifier",
            evaluator_identity_digest="5" * 64,
            verifier_identity_digest="6" * 64,
            tested_model_digest="1" * 64,
            verifier_model_digest="2" * 64,
            environment_digest="3" * 64,
            trial_count=trials,
            passed_trials=passed,
            score_basis_points=score,
            evaluated_at="2026-08-16T08:00:00Z",
        )

    def plan(self):
        candidate = self.candidate()
        evaluation = self.evaluation(candidate)
        plan = prepare_skill_activation(
            self.resolver,
            self.policy,
            candidate,
            evaluation,
            expected_registry_digest=None,
            rollback_target_ref="registry:empty",
            approver_identity_digest="7" * 64,
        )
        return candidate, evaluation, plan

    @staticmethod
    def authorize(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "skill-registry-approval",
                approved=True,
            ),
        )

    def test_candidate_and_evaluation_are_content_free_and_digest_bound(self) -> None:
        candidate = self.candidate()
        evaluation = self.evaluation(candidate)
        serialized = json.dumps(
            {"candidate": candidate.as_payload(), "evaluation": evaluation.as_payload()}
        )
        windows_marker = "C:" + chr(92)
        self.assertNotIn(windows_marker, serialized)
        self.assertNotIn('"code":', serialized.lower())
        self.assertNotIn('"content":', serialized.lower())
        self.assertFalse(candidate.as_payload()["invariants"]["skill_content_included"])
        self.assertFalse(candidate.as_payload()["invariants"]["grants_authority"])
        tampered = copy.deepcopy(candidate.as_payload())
        tampered["source_digest"] = "9" * 64
        with self.assertRaisesRegex(SkillLifecycleError, "digest"):
            parse_skill_candidate(tampered)
        tampered = copy.deepcopy(evaluation.as_payload())
        tampered["score_basis_points"] = 10000
        with self.assertRaisesRegex(SkillLifecycleError, "digest"):
            parse_skill_evaluation(tampered)

    def test_candidate_rejects_physical_path_and_secret_like_reference(self) -> None:
        with self.assertRaisesRegex(SkillLifecycleError, "logical reference|physical path"):
            build_skill_candidate(
                candidate_id="bad-candidate",
                skill_id="context-curator",
                proposed_by_ref="actor:C:" + chr(92) + "private" + chr(92) + "file",
                proposer_identity_digest="4" * 64,
                source_refs=["research:one"],
                source_digest="a" * 64,
                repetition_digests=["b" * 64],
                proposer_model_digest="c" * 64,
            )
        with self.assertRaisesRegex(SkillLifecycleError, "secret"):
            build_skill_candidate(
                candidate_id="bad-candidate",
                skill_id="context-curator",
                proposed_by_ref="actor:token=abcdefgh",
                proposer_identity_digest="4" * 64,
                source_refs=["research:one"],
                source_digest="a" * 64,
                repetition_digests=["b" * 64],
                proposer_model_digest="c" * 64,
            )

    def test_source_and_repetition_dedupe_is_deterministic(self) -> None:
        first = self.candidate("candidate-one", "a")
        second = self.candidate("candidate-two", "a")
        third = build_skill_candidate(
            candidate_id="candidate-three",
            skill_id="context-curator",
            proposed_by_ref="actor:three",
            proposer_identity_digest="4" * 64,
            source_refs=["research:other"],
            source_digest="9" * 64,
            repetition_digests=["8" * 64],
            proposer_model_digest="7" * 64,
        )
        self.assertEqual(
            ({
                "canonical_candidate_id": "candidate-one",
                "duplicate_candidate_ids": ["candidate-two"],
                "evidence_weight": 1,
            },),
            find_skill_candidate_duplicates([third, second, first]),
        )

    def test_independent_verifier_identity_and_model_are_required(self) -> None:
        candidate = self.candidate()
        arguments = dict(
            evaluation_id="context-evaluation",
            project_fixture_digest="e" * 64,
            evaluation_run_digest="f" * 64,
            tested_model_digest="1" * 64,
            verifier_model_digest="2" * 64,
            environment_digest="3" * 64,
            evaluator_identity_digest="5" * 64,
            verifier_identity_digest="6" * 64,
            trial_count=3,
            passed_trials=3,
            score_basis_points=9500,
            evaluated_at="2026-08-16T08:00:00Z",
        )
        with self.assertRaisesRegex(SkillLifecycleError, "verifier identity"):
            build_skill_evaluation(
                self.policy,
                candidate,
                evaluator_ref="actor:same",
                verifier_ref="actor:same",
                **arguments,
            )
        alias_arguments = dict(arguments)
        alias_arguments["evaluator_identity_digest"] = candidate.proposer_identity_digest
        with self.assertRaisesRegex(SkillLifecycleError, "must be distinct"):
            build_skill_evaluation(
                self.policy,
                candidate,
                evaluator_ref="actor:proposer-alias",
                verifier_ref="actor:verifier",
                **alias_arguments,
            )
        arguments["verifier_model_digest"] = arguments["tested_model_digest"]
        with self.assertRaisesRegex(SkillLifecycleError, "verifier model"):
            build_skill_evaluation(
                self.policy,
                candidate,
                evaluator_ref="actor:evaluator",
                verifier_ref="actor:verifier",
                **arguments,
            )

    def test_insufficient_trials_or_threshold_cannot_request_approval(self) -> None:
        candidate = self.candidate()
        for evaluation in (
            self.evaluation(candidate, trials=2, passed=2),
            self.evaluation(candidate, trials=3, passed=2),
            self.evaluation(candidate, trials=10, passed=3),
            self.evaluation(candidate, trials=3, passed=3, score=8999),
        ):
            self.assertEqual("failed", evaluation.outcome)
            with self.assertRaisesRegex(SkillLifecycleError, "failed evaluation"):
                prepare_skill_activation(
                    self.resolver,
                    self.policy,
                    candidate,
                    evaluation,
                    expected_registry_digest=None,
                    rollback_target_ref="registry:empty",
                    approver_identity_digest="7" * 64,
                )

    def test_activation_is_exact_approved_and_candidate_cannot_self_promote(self) -> None:
        candidate, evaluation, plan = self.plan()
        self.assertEqual("approval-required", plan.as_payload()["state"])
        self.assertTrue(plan.mutation.approval_required)
        self.assertEqual("user-data", plan.mutation.ownership)
        with self.assertRaises(MutationGateError):
            authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            )
        authorization = self.authorize(plan)
        with self.assertRaisesRegex(SkillLifecycleError, "stable identity"):
            finalize_skill_registry_change(
                plan,
                authorization,
                changed_by_ref="actor:proposer-alias",
                changed_by_identity_digest=candidate.proposer_identity_digest,
            )
        with self.assertRaisesRegex(SkillLifecycleError, "must be distinct"):
            prepare_skill_activation(
                self.resolver,
                self.policy,
                candidate,
                evaluation,
                expected_registry_digest=None,
                rollback_target_ref="registry:empty",
                approver_identity_digest=candidate.proposer_identity_digest,
            )
        alias_plan = copy.deepcopy(plan.as_payload())
        alias_plan["approver_identity_digest"] = candidate.proposer_identity_digest
        identity = {
            key: value for key, value in alias_plan.items()
            if key not in {"schema_ref", "schema_version", "plan_digest"}
        }
        alias_plan["plan_digest"] = hashlib.sha256(canonical_json(identity)).hexdigest()
        with self.assertRaisesRegex(SkillLifecycleError, "must be distinct"):
            parse_skill_registry_change_plan(alias_plan)
        active = finalize_skill_registry_change(
            plan,
            authorization,
            changed_by_ref="actor:registry-owner",
            changed_by_identity_digest="7" * 64,
        )
        self.assertEqual("active", active.state)
        self.assertFalse(active.as_payload()["invariants"]["grants_authority"])

    def test_plan_and_lifecycle_tamper_are_rejected(self) -> None:
        _, _, plan = self.plan()
        tampered = copy.deepcopy(plan.as_payload())
        tampered["rollback_target_ref"] = "registry:other"
        with self.assertRaisesRegex(SkillLifecycleError, "digest"):
            parse_skill_registry_change_plan(tampered)
        active = finalize_skill_registry_change(
            plan,
            self.authorize(plan),
            changed_by_ref="actor:registry-owner",
            changed_by_identity_digest="7" * 64,
        )
        tampered_record = copy.deepcopy(active.as_payload())
        tampered_record["state"] = "retired"
        with self.assertRaises(SkillLifecycleError):
            parse_skill_lifecycle_record(tampered_record)

    def test_active_skill_can_be_deprecated_or_retired_only_via_new_exact_plan(self) -> None:
        _, _, activation = self.plan()
        active = finalize_skill_registry_change(
            activation,
            self.authorize(activation),
            changed_by_ref="actor:registry-owner",
            changed_by_identity_digest="7" * 64,
        )
        deprecation = prepare_skill_state_change(
            self.resolver,
            active,
            to_state="deprecated",
            rollback_target_ref="skill:context-curator@active",
            approver_identity_digest="7" * 64,
            supersedes_ref="skill:context-curator-v2",
        )
        deprecated = finalize_skill_registry_change(
            deprecation,
            self.authorize(deprecation),
            changed_by_ref="actor:lifecycle-reviewer",
            changed_by_identity_digest="7" * 64,
        )
        self.assertEqual("deprecated", deprecated.state)
        retirement = prepare_skill_state_change(
            self.resolver,
            deprecated,
            to_state="retired",
            rollback_target_ref="skill:context-curator@deprecated",
            approver_identity_digest="7" * 64,
        )
        retired = finalize_skill_registry_change(
            retirement,
            self.authorize(retirement),
            changed_by_ref="actor:registry-owner",
            changed_by_identity_digest="7" * 64,
        )
        self.assertEqual("retired", retired.state)

    def test_public_contracts_match_strict_json_schemas(self) -> None:
        candidate, evaluation, plan = self.plan()
        active = finalize_skill_registry_change(
            plan,
            self.authorize(plan),
            changed_by_ref="actor:registry-owner",
            changed_by_identity_digest="7" * 64,
        )
        payloads = (
            ("skill-lifecycle-policy.schema.json", json.loads((REPO_ROOT / "config" / "skill-lifecycle-policy.json").read_text(encoding="utf-8"))),
            ("skill-candidate.schema.json", candidate.as_payload()),
            ("skill-evaluation.schema.json", evaluation.as_payload()),
            ("skill-registry-change-plan.schema.json", plan.as_payload()),
            ("skill-lifecycle-record.schema.json", active.as_payload()),
        )
        for name, payload in payloads:
            schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)), name)


if __name__ == "__main__":
    unittest.main()

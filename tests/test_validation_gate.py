from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.validation_gate import (  # noqa: E402
    ValidationGateError,
    build_validation_gate,
    parse_validation_gate,
    validate_gate_verification,
)
from krcn_core.orchestration_verifier import (  # noqa: E402
    SubjectVerification,
    TaskVerification,
    VerificationEvidence,
)


def sha(character: str) -> str:
    return character * 64


def verifier(*, actor_digest: str = sha("8")):
    return create_agent_execution_identity(
        task_id="task-one", plan_id=sha("a"), step_id="verify-effect", role="verifier",
        actor_digest=actor_digest, session_digest=sha("9"), assignment_digest=sha("7"),
        runtime_kind="isolated-role",
    )


def gate(**overrides):
    subject_one = sha("1")
    subject_two = sha("2")
    values = {
        "project_id": "project-one", "work_item_id": "work-one", "task_id": "task-one",
        "task_plan_id": sha("a"), "worker_step_id": "apply-change",
        "effect_id": "write-change", "effect_type": "write", "effect_digest": sha("b"),
        "effect_authorization_id": sha("c"), "worker_execution_identity_id": sha("d"),
        "worker_actor_digest": sha("e"), "verifier_execution_identity": verifier(),
        "subjects": [
            {"subject_kind": "acceptance-criterion", "subject_digest": subject_one},
            {"subject_kind": "verification-requirement", "subject_digest": subject_two},
        ],
        "checks": [
            {"check_id": "compile-check", "actor_kind": "code", "method": "command",
             "expected_result": "exit-0", "evidence_required": ["test-result"],
             "subject_digests": [subject_one]},
            {"check_id": "policy-check", "actor_kind": "verifier", "method": "evidence-review",
             "expected_result": "passed", "evidence_required": ["policy-decision", "state-observation"],
             "subject_digests": [subject_two]},
        ],
        "policy_revision": sha("f"), "source_revision_digest": sha("0"),
        "created_at": "2026-08-17T15:00:00.000Z", "mutation_plan_id": sha("3"),
        "provider_request_id": None,
    }
    values.update(overrides)
    return build_validation_gate(**values)


class ValidationGateTests(unittest.TestCase):
    def test_gate_is_deterministic_strict_and_schema_valid(self) -> None:
        first = gate()
        second = gate(subjects=list(reversed(gate().payload["subjects"])), checks=list(reversed(gate().payload["checks"])))
        self.assertEqual(first.validation_gate_id, second.validation_gate_id)
        self.assertEqual(first.as_dict(), parse_validation_gate(first.as_dict()).as_dict())
        schema = json.loads((REPO_ROOT / "schemas/validation-gate.schema.json").read_text(encoding="utf-8"))
        identity_schema = json.loads((REPO_ROOT / "schemas/agent-execution-identity.schema.json").read_text(encoding="utf-8"))
        registry = Registry().with_resource(identity_schema["$id"], Resource.from_contents(identity_schema))
        self.assertEqual([], list(Draft202012Validator(schema, registry=registry).iter_errors(first.as_dict())))

    def test_worker_and_verifier_must_be_independent(self) -> None:
        with self.assertRaisesRegex(ValidationGateError, "independent"):
            gate(worker_actor_digest=sha("8"))
        wrong_task = create_agent_execution_identity(
            task_id="task-two", plan_id=sha("a"), step_id="verify-effect", role="verifier",
            actor_digest=sha("8"), session_digest=sha("9"), assignment_digest=sha("7"), runtime_kind="isolated-role",
        )
        with self.assertRaisesRegex(ValidationGateError, "independent"):
            gate(verifier_execution_identity=wrong_task)

    def test_effect_authorization_rules_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValidationGateError, "mutation plan"):
            gate(mutation_plan_id=None)
        with self.assertRaisesRegex(ValidationGateError, "provider request"):
            gate(effect_type="network", mutation_plan_id=None, provider_request_id=None)
        network = gate(effect_type="network", mutation_plan_id=None, provider_request_id=sha("4"))
        self.assertEqual("network", network.payload["bindings"]["effect_type"])

    def test_check_matrix_must_cover_exact_subject_set(self) -> None:
        subject = sha("1")
        incomplete = [{"check_id": "compile-check", "actor_kind": "code", "method": "command",
                       "expected_result": "exit-0", "evidence_required": ["test-result"],
                       "subject_digests": [subject]}]
        with self.assertRaisesRegex(ValidationGateError, "exact subjects"):
            gate(checks=incomplete)
        duplicate = gate().as_dict()["checks"] * 2
        with self.assertRaisesRegex(ValidationGateError, "canonical"):
            gate(checks=duplicate)

    def test_gate_cannot_be_derived_after_execution_or_tampered(self) -> None:
        payload = gate().as_dict()
        payload["safety"]["derived_after_execution"] = True
        with self.assertRaisesRegex(ValidationGateError, "safety"):
            parse_validation_gate(payload)
        payload = gate().as_dict()
        payload["bindings"]["effect_digest"] = sha("5")
        with self.assertRaisesRegex(ValidationGateError, "digest"):
            parse_validation_gate(payload)

    def test_unknown_fields_and_noncanonical_time_are_rejected(self) -> None:
        payload = gate().as_dict()
        payload["raw_output"] = "x"
        with self.assertRaisesRegex(ValidationGateError, "fields"):
            parse_validation_gate(payload)
        with self.assertRaisesRegex(ValidationGateError, "canonical"):
            gate(created_at="2026-08-17T15:00:00Z")

    def test_post_verification_must_match_gate_subjects_checks_and_identity(self) -> None:
        checked_gate = gate()
        verifier_identity = verifier()
        subject_one = sha("1")
        subject_two = sha("2")
        evidence = (
            VerificationEvidence("compile-evidence", "test-result", "acceptance-criterion", subject_one,
                                 "verify-effect", verifier_identity.execution_identity_id, ("apply-change",),
                                 (sha("4"),), True, sha("5")),
            VerificationEvidence("policy-evidence", "policy-decision", "verification-requirement", subject_two,
                                 "verify-effect", verifier_identity.execution_identity_id, ("apply-change",),
                                 (sha("6"),), True, sha("7")),
            VerificationEvidence("state-evidence", "state-observation", "verification-requirement", subject_two,
                                 "verify-effect", verifier_identity.execution_identity_id, ("apply-change",),
                                 (sha("8"),), True, sha("9")),
        )
        verification = TaskVerification(
            "task-one", sha("a"), sha("c"), (sha("0"),), (sha("d"),),
            (verifier_identity,), evidence,
            (SubjectVerification("acceptance-criterion", subject_one, ("compile-evidence",), True),
             SubjectVerification("verification-requirement", subject_two, ("policy-evidence", "state-evidence"), True)),
            (), "verified", True, sha("f"),
        )
        self.assertTrue(validate_gate_verification(checked_gate, verification))
        incomplete = TaskVerification(
            verification.task_id, verification.plan_id, verification.authorization_id,
            verification.worker_checkpoint_ids, verification.worker_execution_identity_ids,
            verification.verifier_execution_identities, evidence[:2], verification.subjects,
            (), "verified", True, sha("e"),
        )
        with self.assertRaisesRegex(ValidationGateError, "incomplete"):
            validate_gate_verification(checked_gate, incomplete)


if __name__ == "__main__":
    unittest.main()

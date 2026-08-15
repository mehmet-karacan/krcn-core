from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.architecture_contracts import (  # noqa: E402
    ArchitectureContractError,
    CONTRACTS_REF,
    main,
    resolve_architecture_contracts,
    validate_architecture_contracts,
    validate_architecture_contracts_repository,
)
from krcn_core.doctor import run_doctor  # noqa: E402


FROZEN_CONTRACT_IDS = {
    "ownership-classes",
    "exact-plan-approval",
    "provider-disclosure",
    "work-graph-authoritative",
    "source-read-in-place",
    "stale-fail-closed",
    "queue-lease-fencing",
    "independent-verifier",
    "records-grant-no-authority",
    "model-decision-grants-no-authority",
    "single-root-execution",
    "json-authoritative-projection-rebuildable",
    "user-policies-preserved",
}


def _contract_repo(root: Path) -> Path:
    """Copy the evidence surface the contracts resolve against into a temp tree."""

    for relative in ("config", "docs/specifications", "docs/adr"):
        source = REPO_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    return root


class ArchitectureContractRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(
            (REPO_ROOT / CONTRACTS_REF).read_text(encoding="utf-8")
        )

    def test_record_is_valid_and_freezes_every_v1_contract(self) -> None:
        self.assertEqual([], validate_architecture_contracts(self.payload))
        self.assertEqual(
            FROZEN_CONTRACT_IDS,
            {contract["id"] for contract in self.payload["contracts"]},
        )

    def test_decision_record_exists_and_states_each_contract(self) -> None:
        decision = REPO_ROOT / self.payload["decision_ref"]
        self.assertTrue(decision.is_file())
        text = decision.read_text(encoding="utf-8")
        self.assertIn("Kabul edildi", text)
        self.assertIn(CONTRACTS_REF, text)
        for number in range(1, len(FROZEN_CONTRACT_IDS) + 1):
            self.assertIn(f"\n{number}. ", text)

    def test_every_contract_carries_at_least_one_code_or_policy_binding(self) -> None:
        for contract in self.payload["contracts"]:
            kinds = {evidence["kind"] for evidence in contract["evidence"]}
            self.assertTrue(
                kinds & {"module-symbol", "policy-flag", "policy-members"},
                f"{contract['id']} has no executable binding",
            )

    def test_duplicate_contract_identifiers_are_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["contracts"].append(payload["contracts"][0])
        self.assertIn(
            f"contracts[{len(FROZEN_CONTRACT_IDS)}] id is duplicated: ownership-classes",
            validate_architecture_contracts(payload),
        )

    def test_unsupported_evidence_kind_is_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["contracts"][0]["evidence"][0] = {"kind": "vibes"}
        self.assertIn(
            "contracts[0].evidence[0] kind is unsupported",
            validate_architecture_contracts(payload),
        )


class ArchitectureContractResolutionTests(unittest.TestCase):
    def test_repository_satisfies_every_frozen_contract(self) -> None:
        resolutions = resolve_architecture_contracts(REPO_ROOT)
        self.assertEqual(len(FROZEN_CONTRACT_IDS), len(resolutions))
        for resolution in resolutions:
            self.assertTrue(resolution.satisfied, resolution.errors)
        self.assertEqual([], validate_architecture_contracts_repository(REPO_ROOT))

    def test_relaxed_policy_flag_breaks_its_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _contract_repo(Path(directory))
            policy_path = root / "config" / "unified-retrieval.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["stale_index_allowed"] = True
            policy_path.write_text(
                json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = validate_architecture_contracts_repository(root)
        self.assertTrue(
            any("stale_index_allowed" in error for error in errors), errors
        )

    def test_removed_ownership_class_breaks_its_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _contract_repo(Path(directory))
            manifest_path = root / "config" / "ownership-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["classes"] = [
                item for item in manifest["classes"] if item.get("id") != "secrets"
            ]
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = validate_architecture_contracts_repository(root)
        self.assertTrue(
            any("classes.secrets" in error for error in errors), errors
        )

    def test_deleted_normative_statement_breaks_its_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _contract_repo(Path(directory))
            specification = root / "docs" / "specifications" / "MODEL-ROUTING.md"
            specification.write_text(
                "# Model routing\n\nRouting picks a profile.\n", encoding="utf-8"
            )
            errors = validate_architecture_contracts_repository(root)
        self.assertTrue(
            any("MODEL-ROUTING.md" in error for error in errors), errors
        )

    def test_missing_decision_record_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _contract_repo(Path(directory))
            (root / "docs" / "adr" / "ADR-013-V1-DEGISMEZ-MIMARI-SOZLESMELERI.md").unlink()
            errors = validate_architecture_contracts_repository(root)
        self.assertTrue(
            any("missing architecture decision record" in error for error in errors),
            errors,
        )

    def test_missing_contract_record_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ArchitectureContractError):
                resolve_architecture_contracts(Path(directory))


class ArchitectureContractCommandTests(unittest.TestCase):
    def test_text_output_lists_every_contract(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--repo", str(REPO_ROOT)])
        rendered = output.getvalue()
        self.assertEqual(0, result)
        for contract_id in FROZEN_CONTRACT_IDS:
            self.assertIn(f"- {contract_id}: ok", rendered)

    def test_json_output_reports_satisfied_contracts(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--repo", str(REPO_ROOT), "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(0, result)
        self.assertTrue(all(item["satisfied"] for item in payload["contracts"]))

    def test_unmet_contract_fails_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _contract_repo(Path(directory))
            policy_path = root / "config" / "provider-policy.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["implicit_provider_discovery"] = True
            policy_path.write_text(
                json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            error = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(error):
                result = main(["--repo", str(root)])
        self.assertEqual(1, result)
        self.assertIn("unmet contract: provider-disclosure", error.getvalue())

    def test_doctor_reports_the_contract_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checks = run_doctor(REPO_ROOT, Path(directory))
        by_id = {item.check_id: item for item in checks}
        self.assertTrue(by_id["v1-architecture-contracts"].passed)


if __name__ == "__main__":
    unittest.main()

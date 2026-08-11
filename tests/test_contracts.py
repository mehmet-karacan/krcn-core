from __future__ import annotations

import json
import unittest
from pathlib import Path


PROPOSED_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCHEMA_NAMES = {
    "agent-result.schema.json",
    "agent.schema.json",
    "context-package.schema.json",
    "default-policy.schema.json",
    "engine.schema.json",
    "project.schema.json",
    "skill.schema.json",
    "task.schema.json",
    "workspace.schema.json",
}


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def package_schema_paths() -> list[Path]:
    schema_root = PROPOSED_ROOT / "schemas"
    return [schema_root / name for name in sorted(PACKAGE_SCHEMA_NAMES)]


def package_text_paths() -> list[Path]:
    paths = list((PROPOSED_ROOT / ".ai").rglob("*"))
    paths.extend(package_schema_paths())
    paths.extend(
        [
            PROPOSED_ROOT / "config" / "ownership-manifest.json",
            PROPOSED_ROOT / "docs" / "adr" / "ADR-003-MAKINE-SOZLESMESI-DILI.md",
            Path(__file__).resolve(),
        ]
    )
    return [path for path in paths if path.is_file()]


class PackageOneContractTests(unittest.TestCase):
    def test_every_json_document_parses(self) -> None:
        documents = list(PROPOSED_ROOT.rglob("*.json"))
        self.assertGreaterEqual(len(documents), 10)
        for document in documents:
            with self.subTest(document=document.relative_to(PROPOSED_ROOT)):
                load_json(document)

    def test_machine_contracts_do_not_use_yaml(self) -> None:
        yaml_documents = list(PROPOSED_ROOT.rglob("*.yaml")) + list(
            PROPOSED_ROOT.rglob("*.yml")
        )
        self.assertEqual(yaml_documents, [])

    def test_schema_references_resolve(self) -> None:
        contract_roots = [PROPOSED_ROOT / ".ai"]
        for contract_root in contract_roots:
            for document in contract_root.rglob("*.json"):
                payload = load_json(document)
                self.assertIsInstance(payload, dict)
                schema_ref = payload.get("schema_ref")
                if schema_ref:
                    resolved = (document.parent / schema_ref).resolve()
                    self.assertTrue(resolved.is_file(), document)

    def test_schema_identifiers_use_krcn_namespace(self) -> None:
        identifiers: set[str] = set()
        for schema_path in package_schema_paths():
            payload = load_json(schema_path)
            self.assertIsInstance(payload, dict)
            identifier = payload.get("$id")
            self.assertIsInstance(identifier, str)
            self.assertTrue(identifier.startswith("urn:krcn:schemas:"), schema_path)
            self.assertNotIn(identifier, identifiers)
            identifiers.add(identifier)

    def test_engine_and_agent_output_contracts_exist(self) -> None:
        schema_ids = {
            load_json(path)["$id"] for path in package_schema_paths()
        }
        contract_documents = list((PROPOSED_ROOT / ".ai" / "engines").glob("*.json"))
        contract_documents += list(
            (PROPOSED_ROOT / ".ai" / "registry" / "agents").glob("*.json")
        )
        for document in contract_documents:
            payload = load_json(document)
            contract = payload.get("output_schema") or payload.get("output_contract")
            if contract:
                self.assertIn(contract, schema_ids, document)

    def test_default_policy_is_offline_and_non_destructive(self) -> None:
        policy = load_json(PROPOSED_ROOT / ".ai" / "policies" / "default.json")
        self.assertEqual(policy["network"]["default"], "deny")
        self.assertTrue(policy["network"]["explicit_opt_in_required"])
        self.assertFalse(policy["network"]["implicit_provider_discovery"])
        self.assertTrue(policy["mutation"]["dry_run_required"])
        self.assertFalse(policy["mutation"]["overwrite_existing"])
        self.assertTrue(policy["mutation"]["rollback_required"])

    def test_only_worker_may_mutate(self) -> None:
        agents_root = PROPOSED_ROOT / ".ai" / "registry" / "agents"
        permissions = {
            path.stem: load_json(path)["may_mutate"] for path in agents_root.glob("*.json")
        }
        self.assertEqual(
            permissions,
            {"explorer": False, "verifier": False, "worker": True},
        )

    def test_ai_contracts_are_owned_by_core(self) -> None:
        manifest = load_json(PROPOSED_ROOT / "config" / "ownership-manifest.json")
        core = next(item for item in manifest["classes"] if item["id"] == "core")
        self.assertIn(".ai/**", core["paths"])

    def test_legacy_namespace_and_long_dash_are_absent(self) -> None:
        forbidden_dashes = {chr(0x2013), chr(0x2014)}
        legacy_namespace = "urn:" + "yz:"
        for path in package_text_paths():
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(legacy_namespace, content, path)
            self.assertFalse(forbidden_dashes.intersection(content), path)


if __name__ == "__main__":
    unittest.main()

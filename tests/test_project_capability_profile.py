from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.discovery import DiscoveryResult, FileEvidence  # noqa: E402
from krcn_core.project_capability_profile import (  # noqa: E402
    ProjectCapabilityProfileError,
    _digest,
    build_project_capability_profile,
    load_project_capability_profiler_policy,
    parse_project_capability_profile,
    project_capability_profile_is_current,
    project_capability_public_summary,
)
from krcn_core.source_bindings import SourceBinding, SourceLocator  # noqa: E402


def discovery_for(root: Path, project_id: str = "sample") -> tuple[SourceBinding, DiscoveryResult]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        suffix = path.suffix.casefold()
        kind = "configuration" if path.name.casefold() in {
            "package.json",
            "pom.xml",
            "pyproject.toml",
            "build.gradle",
            "dockerfile",
        } or suffix in {".json", ".toml", ".xml", ".yml", ".yaml"} else "source"
        files.append(
            FileEvidence(
                path.relative_to(root).as_posix(),
                kind,
                len(content),
                hashlib.sha256(content).hexdigest(),
            )
        )
    identity = [item.as_dict() for item in files]
    root_digest = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    binding = SourceBinding(
        1,
        f"{project_id}-local",
        project_id,
        "project",
        SourceLocator("local-path", str(root.resolve())),
        "read-only",
        ("read", "metadata", "search", "index"),
        (),
        1,
    )
    return binding, DiscoveryResult(
        binding.binding_id,
        project_id,
        1,
        root_digest,
        tuple(files),
        (),
        {"blocked": 0, "symlink": 0, "too_large": 0, "unstable": 0, "unreadable": 0},
    )


def capability_ids(profile: dict[str, object]) -> set[str]:
    dimensions = profile["dimensions"]
    return {
        item["capability_id"]
        for signals in dimensions.values()
        for item in signals
    }


class ProjectCapabilityProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _profile(self, project_id: str = "sample") -> tuple[dict[str, object], SourceBinding, DiscoveryResult]:
        binding, discovery = discovery_for(self.root, project_id)
        profile = build_project_capability_profile(
            REPO_ROOT,
            self.root,
            project_id,
            binding,
            discovery,
        )
        return profile, binding, discovery

    def test_node_frontend_profile_is_module_scoped_and_deterministic(self) -> None:
        web = self.root / "apps" / "web"
        web.mkdir(parents=True)
        (web / "package.json").write_text(
            json.dumps(
                {
                    "dependencies": {"react": "18.3.0", "next": "15.0.0"},
                    "devDependencies": {"jest": "30.0.0", "eslint": "9.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (web / "src").mkdir()
        (web / "src" / "page.tsx").write_text("export default function Page() { return null; }\n", encoding="utf-8")
        profile, binding, discovery = self._profile("web-suite")
        found = capability_ids(profile)
        self.assertTrue({"nodejs", "npm", "react", "nextjs", "jest", "eslint", "frontend"}.issubset(found))
        self.assertNotIn("backend", found)
        self.assertIn("ui-analysis", {item["workload_id"] for item in profile["workload_profiles"]})
        self.assertTrue(project_capability_profile_is_current(REPO_ROOT, profile, "web-suite", binding, discovery))
        again = build_project_capability_profile(REPO_ROOT, self.root, "web-suite", binding, discovery)
        self.assertEqual(profile, again)
        summary = project_capability_public_summary(profile)
        self.assertFalse(summary["paths_disclosed"])
        self.assertNotIn(str(self.root), json.dumps(summary))

    def test_java_spring_oracle_profile_uses_direct_manifest_dependencies(self) -> None:
        backend = self.root / "backend"
        backend.mkdir()
        (backend / "pom.xml").write_text(
            """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>example</groupId><artifactId>api</artifactId><version>1</version>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>com.oracle.database.jdbc</groupId><artifactId>ojdbc11</artifactId></dependency>
    <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId></dependency>
  </dependencies>
</project>""",
            encoding="utf-8",
        )
        profile, _, discovery = self._profile("spring-api")
        found = capability_ids(profile)
        self.assertTrue({"java", "maven", "spring-boot", "spring-web", "backend", "oracle", "junit"}.issubset(found))
        self.assertNotIn("api", found)
        for evidence in profile["evidence_catalog"]:
            current = next(item for item in discovery.files if item.relative_path == evidence["relative_path"])
            self.assertEqual(current.sha256, evidence["file_digest"])

    def test_python_and_database_workloads_are_discovered_without_source_copy(self) -> None:
        (self.root / "pyproject.toml").write_text(
            """[project]
name = "data-api"
dependencies = ["fastapi>=0.115", "oracledb>=2", "psycopg>=3", "pytest>=8"]
[tool.ruff]
line-length = 100
""",
            encoding="utf-8",
        )
        sql = self.root / "database" / "packages"
        sql.mkdir(parents=True)
        (sql / "metadata.pkb").write_text(
            "create or replace package body metadata as\n"
            "  procedure load is begin dbms_metadata.get_ddl('TABLE', 'T'); end;\n"
            "end;\n",
            encoding="utf-8",
        )
        before = {
            path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.root.rglob("*") if path.is_file()
        }
        profile, _, _ = self._profile("data-api")
        after = {
            path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        found = capability_ids(profile)
        self.assertTrue({"python", "fastapi", "oracle", "postgresql", "pytest", "ruff", "plsql", "oracle-metadata", "database-development"}.issubset(found))
        workloads = {item["workload_id"]: item for item in profile["workload_profiles"]}
        self.assertEqual("local-only", workloads["database-analysis"]["fixture_policy"])
        self.assertFalse(profile["invariants"]["source_content_included"])

    def test_shallow_markers_do_not_invent_framework_or_database(self) -> None:
        (self.root / "package.json").write_text(json.dumps({"name": "plain-node"}), encoding="utf-8")
        (self.root / "notes.sql").write_text("select value from settings;\n", encoding="utf-8")
        (self.root / "README.md").write_text("React Spring Oracle PostgreSQL\n", encoding="utf-8")
        profile, _, _ = self._profile()
        found = capability_ids(profile)
        self.assertTrue({"nodejs", "npm"}.issubset(found))
        self.assertTrue({"react", "spring-boot", "oracle", "postgresql", "frontend", "backend"}.isdisjoint(found))

    def test_sensitive_manifest_is_skipped_without_disclosing_value(self) -> None:
        secret_value = "github_pat_" + "A" * 30
        (self.root / "package.json").write_text(
            json.dumps({"dependencies": {"react": "18"}, "serviceToken": secret_value}),
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        serialized = json.dumps(profile)
        self.assertNotIn(secret_value, serialized)
        self.assertNotIn("react", capability_ids(profile))
        self.assertEqual(1, profile["limitations"]["sensitive_content_skipped"])
        self.assertEqual([], profile["evidence_catalog"])

    def test_tampered_evidence_and_source_state_are_rejected(self) -> None:
        (self.root / "package.json").write_text(json.dumps({"dependencies": {"react": "18"}}), encoding="utf-8")
        profile, binding, discovery = self._profile()
        tampered = json.loads(json.dumps(profile))
        tampered["evidence_catalog"][0]["relative_path"] = "../escape.json"
        with self.assertRaises(ProjectCapabilityProfileError):
            parse_project_capability_profile(tampered)
        (self.root / "package.json").write_text(json.dumps({"dependencies": {"react": "19"}}), encoding="utf-8")
        _, changed = discovery_for(self.root)
        self.assertFalse(project_capability_profile_is_current(REPO_ROOT, profile, "sample", binding, changed))
        with self.assertRaises(ProjectCapabilityProfileError):
            parse_project_capability_profile(profile, discovery=changed)

    def test_author_email_does_not_hide_safe_manifest_capabilities(self) -> None:
        (self.root / "package.json").write_text(
            json.dumps(
                {
                    "author": {"email": "developer" + "@" + "example.invalid"},
                    "dependencies": {"react": "18"},
                }
            ),
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertTrue({"nodejs", "react", "frontend"}.issubset(capability_ids(profile)))
        self.assertEqual(0, profile["limitations"]["sensitive_content_skipped"])

    def test_secret_path_marker_does_not_emit_evidence(self) -> None:
        secret_value = "github_pat_" + "B" * 30
        (self.root / "Dockerfile").write_text(
            f"FROM scratch\nENV ACCESS_TOKEN={secret_value}\n",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertNotIn("container", capability_ids(profile))
        self.assertEqual(1, profile["limitations"]["sensitive_content_skipped"])
        self.assertNotIn(secret_value, json.dumps(profile))

    def test_invalid_manifest_is_a_limitation_not_an_integration_blocker(self) -> None:
        (self.root / "package.json").write_text("{invalid", encoding="utf-8")
        profile, _, _ = self._profile()
        self.assertEqual(1, profile["limitations"]["invalid_content_skipped"])
        self.assertEqual(set(), capability_ids(profile))

    def test_invalid_manifest_does_not_define_a_module_boundary(self) -> None:
        service = self.root / "apps" / "service"
        service.mkdir(parents=True)
        (service / "package.json").write_text("{invalid", encoding="utf-8")
        (service / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        profile, _, _ = self._profile("invalid-module")
        self.assertIn("container", capability_ids(profile))
        self.assertNotIn(
            "apps/service",
            {item["relative_path"] for item in profile["modules"]},
        )

    def test_maven_dtd_is_rejected_without_expansion(self) -> None:
        (self.root / "pom.xml").write_text(
            "<!DOCTYPE project [<!ENTITY value 'spring-boot-starter-web'>]>"
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>example</groupId><artifactId>&value;</artifactId>"
            "<version>1</version></project>",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertEqual(1, profile["limitations"]["invalid_content_skipped"])
        self.assertTrue({"java", "maven", "spring-boot"}.isdisjoint(capability_ids(profile)))

    def test_nearest_manifest_owns_nested_database_evidence(self) -> None:
        backend = self.root / "backend"
        migration = backend / "src" / "main" / "resources" / "db" / "migration"
        migration.mkdir(parents=True)
        (backend / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion><groupId>x</groupId>"
            "<artifactId>x</artifactId><version>1</version></project>",
            encoding="utf-8",
        )
        (migration / "V1.sql").write_text(
            "create extension if not exists pgcrypto;\n",
            encoding="utf-8",
        )
        profile, _, _ = self._profile("nested")
        postgres = next(
            item
            for item in profile["dimensions"]["databases"]
            if item["capability_id"] == "postgresql"
        )
        self.assertEqual(
            [
                next(
                    item["module_id"]
                    for item in profile["modules"]
                    if item["relative_path"] == "backend"
                )
            ],
            postgres["module_refs"],
        )
        self.assertNotIn("multi-module", capability_ids(profile))

    def test_specialist_workload_only_scopes_matching_modules(self) -> None:
        for relative, dependencies in (
            ("apps/web", {"react": "18"}),
            ("services/api", {"express": "5"}),
        ):
            module = self.root.joinpath(*relative.split("/"))
            module.mkdir(parents=True)
            (module / "package.json").write_text(
                json.dumps({"dependencies": dependencies}),
                encoding="utf-8",
            )
        profile, _, _ = self._profile("full-suite")
        ui = next(
            item
            for item in profile["workload_profiles"]
            if item["workload_id"] == "ui-analysis"
        )
        self.assertEqual(
            [
                next(
                    item["module_id"]
                    for item in profile["modules"]
                    if item["relative_path"] == "apps/web"
                )
            ],
            ui["scope_refs"],
        )
        self.assertIn("full-stack", capability_ids(profile))

    def test_gradle_comment_does_not_invent_spring(self) -> None:
        (self.root / "build.gradle").write_text(
            "plugins { id 'java' }\n// implementation 'org.springframework.boot:spring-boot-starter-web:3'\n",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertTrue({"java", "gradle"}.issubset(capability_ids(profile)))
        self.assertNotIn("spring-web", capability_ids(profile))

    def test_test_scoped_java_dependencies_do_not_create_production_backend(self) -> None:
        (self.root / "pom.xml").write_text(
            """<project><modelVersion>4.0.0</modelVersion>
<groupId>example</groupId><artifactId>sample</artifactId><version>1</version>
<dependencies>
  <dependency><groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId><scope>test</scope></dependency>
  <dependency><groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId><scope>test</scope></dependency>
</dependencies></project>""",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        found = capability_ids(profile)
        self.assertIn("junit", found)
        self.assertTrue({"spring-boot", "spring-web", "backend"}.isdisjoint(found))

    def test_inactive_gradle_plugin_and_test_dependency_do_not_create_backend(self) -> None:
        (self.root / "build.gradle").write_text(
            "plugins { id 'org.springframework.boot' version '3.4.0' apply false }\n"
            "testImplementation 'org.springframework.boot:spring-boot-starter-web:3.4.0'\n"
            "testImplementation 'org.junit.jupiter:junit-jupiter:5.11.0'\n",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        found = capability_ids(profile)
        self.assertIn("junit", found)
        self.assertTrue({"spring-boot", "spring-web", "backend"}.isdisjoint(found))

    def test_documentation_delivery_markers_do_not_create_production_capability(self) -> None:
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        profile, _, _ = self._profile()
        self.assertNotIn("container", capability_ids(profile))

    def test_partial_profile_is_not_authoritative_for_model_assignment(self) -> None:
        secret_value = "github_pat_" + "C" * 30
        (self.root / "Dockerfile").write_text(
            f"FROM scratch\nENV ACCESS_TOKEN={secret_value}\n",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertEqual("partial-safe", profile["coverage_state"])
        self.assertFalse(profile["authoritative_for_model_assignment"])

    def test_nested_drive_and_control_character_paths_are_rejected(self) -> None:
        (self.root / "package.json").write_text(
            json.dumps({"name": "sample"}),
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        for unsafe in ("prefix/C:/private/file", "prefix/D:relative/file", "bad\npath"):
            tampered = json.loads(json.dumps(profile))
            tampered["modules"][0]["relative_path"] = unsafe
            with self.assertRaises(ProjectCapabilityProfileError):
                parse_project_capability_profile(tampered)

    def test_utplsql_annotation_survives_comment_filtering(self) -> None:
        (self.root / "package_test.pks").write_text(
            "create or replace package package_test as\n--%suite(sample)\n--%test(works)\nend;\n",
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertIn("utplsql", capability_ids(profile))

    def test_api_requires_an_explicit_contract_marker(self) -> None:
        (self.root / "openapi.json").write_text(
            json.dumps({"openapi": "3.1.0", "paths": {}}),
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertIn("api", capability_ids(profile))

    def test_example_manifest_does_not_create_production_capability(self) -> None:
        example = self.root / "examples" / "react-demo"
        example.mkdir(parents=True)
        (example / "package.json").write_text(
            json.dumps({"dependencies": {"react": "18"}}),
            encoding="utf-8",
        )
        profile, _, _ = self._profile()
        self.assertTrue({"react", "frontend"}.isdisjoint(capability_ids(profile)))

    def test_binding_and_portable_path_tampering_are_rejected(self) -> None:
        (self.root / "package.json").write_text(json.dumps({"name": "sample"}), encoding="utf-8")
        profile, binding, discovery = self._profile()
        wrong = SourceBinding(
            binding.schema_version,
            binding.binding_id,
            "another-project",
            binding.source_kind,
            binding.locator,
            binding.default_access,
            binding.capabilities,
            binding.policy_refs,
            binding.revision,
        )
        with self.assertRaises(ProjectCapabilityProfileError):
            build_project_capability_profile(REPO_ROOT, self.root, "sample", wrong, discovery)
        tampered = json.loads(json.dumps(profile))
        tampered["modules"][0]["relative_path"] = "C" + ":/workspace/project"
        tampered["capability_digest"] = _digest(
            {
                "modules": tampered["modules"],
                "dimensions": tampered["dimensions"],
                "workload_profiles": tampered["workload_profiles"],
                "limitations": tampered["limitations"],
                "coverage_state": tampered["coverage_state"],
                "authoritative_for_model_assignment": tampered[
                    "authoritative_for_model_assignment"
                ],
            }
        )
        with self.assertRaises(ProjectCapabilityProfileError):
            parse_project_capability_profile(tampered)

    def test_rehashed_policy_conflict_is_not_current(self) -> None:
        (self.root / "package.json").write_text(json.dumps({"name": "sample"}), encoding="utf-8")
        profile, binding, discovery = self._profile()
        tampered = json.loads(json.dumps(profile))
        tampered["dimensions"]["technologies"][0]["name"] = "Fabricated runtime"
        tampered["capability_digest"] = _digest(
            {
                "modules": tampered["modules"],
                "dimensions": tampered["dimensions"],
                "workload_profiles": tampered["workload_profiles"],
                "limitations": tampered["limitations"],
                "coverage_state": tampered["coverage_state"],
                "authoritative_for_model_assignment": tampered[
                    "authoritative_for_model_assignment"
                ],
            }
        )
        tampered["profile_digest"] = _digest(
            {
                "schema_version": 1,
                "project_id": tampered["project_id"],
                "binding_id": tampered["binding_id"],
                "binding_revision": tampered["binding_revision"],
                "source_digest": tampered["source_digest"],
                "profiler_id": tampered["profiler"]["profiler_id"],
                "profiler_revision": tampered["profiler"]["profiler_revision"],
                "policy_digest": tampered["profiler"]["policy_digest"],
                "evidence_digest": tampered["evidence_digest"],
                "capability_digest": tampered["capability_digest"],
            }
        )
        policy = load_project_capability_profiler_policy(REPO_ROOT)
        with self.assertRaises(ProjectCapabilityProfileError):
            parse_project_capability_profile(
                tampered,
                discovery=discovery,
                policy=policy,
            )
        self.assertFalse(
            project_capability_profile_is_current(
                REPO_ROOT,
                tampered,
                "sample",
                binding,
                discovery,
            )
        )


if __name__ == "__main__":
    unittest.main()

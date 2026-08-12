"""Deterministic, evidence-bound capability profiles for read-only projects."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from .discovery import DiscoveryResult, FileEvidence
from .foundation import detect_content_findings, load_json
from .information_records import canonical_json
from .project_metadata import portable_slug
from .source_bindings import SourceBinding


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EVIDENCE_ID = re.compile(r"^evidence-[a-f0-9]{64}$")
CATEGORIES = (
    "technologies",
    "frameworks",
    "architecture",
    "databases",
    "testing",
    "build",
    "delivery",
    "quality",
)
WORKLOAD_KINDS = {
    "analysis",
    "architecture",
    "implementation",
    "verification",
    "code-review",
    "database-analysis",
    "security-review",
    "performance-analysis",
    "embedding",
    "reranking",
}
TRUST_ROLES = {"read-only-worker-agent", "worker-agent", "verifier-agent"}
FIXTURE_POLICIES = {"synthetic-only", "sanitized-derived", "local-only"}
MANIFEST_NAMES = {
    "build.gradle",
    "build.gradle.kts",
    "package.json",
    "pom.xml",
    "pyproject.toml",
}
SQL_SUFFIXES = {".pkb", ".pks", ".plb", ".pls", ".sql", ".tpb", ".tps"}


class ProjectCapabilityProfileError(ValueError):
    """Raised when a capability profile or profiler policy is unsafe."""


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    category: str
    name: str


@dataclass(frozen=True)
class WorkloadDefinition:
    workload_id: str
    workload_kind: str
    trust_role: str
    specialization_profile_id: str
    fixture_policy: str
    benchmark_dimensions: tuple[str, ...]
    evaluation_traits: tuple[str, ...]
    trigger_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ProjectCapabilityProfilerPolicy:
    profiler_id: str
    profiler_revision: int
    maximum_inspected_file_bytes: int
    maximum_inspected_files: int
    maximum_total_inspected_bytes: int
    maximum_evidence_items: int
    minimum_persisted_confidence: float
    confidence_bands: Mapping[str, float]
    capabilities: Mapping[str, CapabilityDefinition]
    workloads: tuple[WorkloadDefinition, ...]
    sensitive_content_detectors: tuple[str, ...]
    policy_digest: str


def _identifier_list(value: object, label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ProjectCapabilityProfileError(f"{label} must be a unique identifier list")
    return tuple(value)


def _safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ProjectCapabilityProfileError(f"{label} must be a portable relative path")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows.drive
        or any(
            ":" in part
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            for part in path.parts
        )
        or ".." in path.parts
        or value.startswith("/")
    ):
        raise ProjectCapabilityProfileError(f"{label} must be a portable relative path")
    if value != "." and path.as_posix() != value:
        raise ProjectCapabilityProfileError(f"{label} must be normalized")
    return value


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def load_project_capability_profiler_policy(
    repo_root: Path,
) -> ProjectCapabilityProfilerPolicy:
    """Load the declarative profiler policy without accepting executable rules."""

    payload = load_json(repo_root / "config" / "project-capability-profiler.json")
    expected = {
        "schema_ref",
        "schema_version",
        "profiler_id",
        "profiler_revision",
        "maximum_inspected_file_bytes",
        "maximum_inspected_files",
        "maximum_total_inspected_bytes",
        "maximum_evidence_items",
        "minimum_persisted_confidence",
        "confidence_bands",
        "capability_catalog",
        "workload_catalog",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ProjectCapabilityProfileError("project capability profiler policy fields are invalid")
    if (
        payload.get("schema_ref")
        != "schemas/project-capability-profiler-policy.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise ProjectCapabilityProfileError("project capability profiler policy schema is invalid")
    profiler_id = payload.get("profiler_id")
    profiler_revision = payload.get("profiler_revision")
    maximum_bytes = payload.get("maximum_inspected_file_bytes")
    maximum_files = payload.get("maximum_inspected_files")
    maximum_total_bytes = payload.get("maximum_total_inspected_bytes")
    maximum_evidence = payload.get("maximum_evidence_items")
    minimum_confidence = payload.get("minimum_persisted_confidence")
    if (
        not isinstance(profiler_id, str)
        or not IDENTIFIER.fullmatch(profiler_id)
        or not isinstance(profiler_revision, int)
        or isinstance(profiler_revision, bool)
        or profiler_revision < 1
        or not isinstance(maximum_bytes, int)
        or isinstance(maximum_bytes, bool)
        or not 1024 <= maximum_bytes <= 1048576
        or not isinstance(maximum_files, int)
        or isinstance(maximum_files, bool)
        or not 1 <= maximum_files <= 100000
        or not isinstance(maximum_total_bytes, int)
        or isinstance(maximum_total_bytes, bool)
        or not 1024 <= maximum_total_bytes <= 1073741824
        or not isinstance(maximum_evidence, int)
        or isinstance(maximum_evidence, bool)
        or not 1 <= maximum_evidence <= 10000
        or not isinstance(minimum_confidence, (int, float))
        or isinstance(minimum_confidence, bool)
        or not 0.5 <= float(minimum_confidence) <= 1.0
    ):
        raise ProjectCapabilityProfileError("project capability profiler limits are invalid")
    bands = payload.get("confidence_bands")
    if (
        not isinstance(bands, dict)
        or set(bands) != {"confirmed", "high", "medium"}
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= float(value) <= 1
            for value in bands.values()
        )
        or not float(bands["confirmed"]) > float(bands["high"]) > float(bands["medium"])
        or float(bands["medium"]) != float(minimum_confidence)
    ):
        raise ProjectCapabilityProfileError("project capability confidence bands are invalid")
    invariants = payload.get("invariants")
    if invariants != {
        "offline_only": True,
        "source_content_persisted": False,
        "secret_values_persisted": False,
        "absolute_paths_persisted": False,
        "grants_authority": False,
    }:
        raise ProjectCapabilityProfileError("project capability profiler invariants are invalid")
    capability_payload = payload.get("capability_catalog")
    if not isinstance(capability_payload, list) or not capability_payload:
        raise ProjectCapabilityProfileError("project capability catalog is invalid")
    capabilities: dict[str, CapabilityDefinition] = {}
    for item in capability_payload:
        if not isinstance(item, dict) or set(item) != {"capability_id", "category", "name"}:
            raise ProjectCapabilityProfileError("project capability definition is invalid")
        capability_id = item.get("capability_id")
        category = item.get("category")
        name = item.get("name")
        if (
            not isinstance(capability_id, str)
            or not IDENTIFIER.fullmatch(capability_id)
            or capability_id in capabilities
            or category not in CATEGORIES
            or not isinstance(name, str)
            or not name
            or len(name) > 100
        ):
            raise ProjectCapabilityProfileError("project capability definition values are invalid")
        capabilities[capability_id] = CapabilityDefinition(capability_id, str(category), name)
    if tuple(capabilities) != tuple(sorted(capabilities)):
        raise ProjectCapabilityProfileError("project capability catalog must be sorted")
    workload_payload = payload.get("workload_catalog")
    if not isinstance(workload_payload, list) or not workload_payload:
        raise ProjectCapabilityProfileError("project workload catalog is invalid")
    workloads = []
    seen_workloads = set()
    for item in workload_payload:
        expected_workload = {
            "workload_id",
            "workload_kind",
            "trust_role",
            "specialization_profile_id",
            "fixture_policy",
            "benchmark_dimensions",
            "evaluation_traits",
            "trigger_capabilities",
        }
        if not isinstance(item, dict) or set(item) != expected_workload:
            raise ProjectCapabilityProfileError("project workload definition is invalid")
        workload_id = item.get("workload_id")
        specialization_profile_id = item.get("specialization_profile_id")
        if (
            not isinstance(workload_id, str)
            or not IDENTIFIER.fullmatch(workload_id)
            or workload_id in seen_workloads
            or item.get("workload_kind") not in WORKLOAD_KINDS
            or item.get("trust_role") not in TRUST_ROLES
            or not isinstance(specialization_profile_id, str)
            or not IDENTIFIER.fullmatch(specialization_profile_id)
            or item.get("fixture_policy") not in FIXTURE_POLICIES
        ):
            raise ProjectCapabilityProfileError("project workload definition values are invalid")
        dimensions = _identifier_list(item.get("benchmark_dimensions"), "benchmark dimensions", allow_empty=False)
        traits = _identifier_list(item.get("evaluation_traits"), "evaluation traits", allow_empty=False)
        triggers = _identifier_list(item.get("trigger_capabilities"), "trigger capabilities")
        if any(item_id not in capabilities for item_id in triggers):
            raise ProjectCapabilityProfileError("project workload references an unknown capability")
        seen_workloads.add(workload_id)
        workloads.append(
            WorkloadDefinition(
                workload_id,
                str(item["workload_kind"]),
                str(item["trust_role"]),
                specialization_profile_id,
                str(item["fixture_policy"]),
                dimensions,
                traits,
                triggers,
            )
        )
    import_policy = load_json(repo_root / "config" / "import-policy.json")
    detectors = import_policy.get("content_detectors")
    if not isinstance(detectors, list) or any(not isinstance(item, str) for item in detectors):
        raise ProjectCapabilityProfileError("project capability sensitive detector policy is invalid")
    sensitive = tuple(
        sorted(
            set(detectors).intersection(
                {
                    "private-key",
                    "github-token",
                    "aws-access-key",
                    "generic-secret-assignment",
                    "credential-uri",
                }
            )
        )
    )
    return ProjectCapabilityProfilerPolicy(
        profiler_id,
        profiler_revision,
        maximum_bytes,
        maximum_files,
        maximum_total_bytes,
        maximum_evidence,
        float(minimum_confidence),
        {key: float(value) for key, value in bands.items()},
        capabilities,
        tuple(workloads),
        sensitive,
        _digest({"profiler_policy": payload, "sensitive_content_detectors": sensitive}),
    )


def _safe_source_file(root: Path, evidence: FileEvidence) -> Path:
    relative = _safe_relative_path(evidence.relative_path, "source evidence path")
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ProjectCapabilityProfileError("project capability evidence contains a symbolic link")
    if not candidate.is_file():
        raise ProjectCapabilityProfileError("project capability evidence is not a regular file")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ProjectCapabilityProfileError("project capability evidence escapes the source root") from exc
    return resolved


def _read_verified_text(root: Path, evidence: FileEvidence) -> str:
    source = _safe_source_file(root, evidence)
    before = source.stat(follow_symlinks=False)
    content = source.read_bytes()
    after = source.stat(follow_symlinks=False)
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or after.st_size != evidence.size
        or hashlib.sha256(content).hexdigest() != evidence.sha256
    ):
        raise ProjectCapabilityProfileError("project source changed after discovery")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProjectCapabilityProfileError("project capability evidence is not UTF-8") from exc
    if "\x00" in text:
        raise ProjectCapabilityProfileError("project capability evidence is binary")
    return text


def _scope(relative_path: str) -> str:
    parts = tuple(part.casefold() for part in PurePosixPath(relative_path).parts)
    if any(part in {"fixtures", "fixture"} for part in parts):
        return "fixture"
    if any(part in {"examples", "example", "samples", "sample"} for part in parts):
        return "example"
    if any(part in {"docs", "doc", "documentation"} for part in parts):
        return "documentation"
    if any(part in {"tests", "test", "spec", "specs", "__tests__"} for part in parts):
        return "test"
    if any(part in {"migration", "migrations", "ddl"} for part in parts):
        return "migration"
    if ".github" in parts or "pipelines" in parts:
        return "ci"
    return "production"


def _module_root(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent.as_posix()
    return "." if parent == "." else parent


def _module_id(project_id: str, relative_path: str) -> str:
    if relative_path == ".":
        return f"{project_id}-root"
    base = portable_slug(f"{project_id}-{relative_path}")
    return f"{base[:48]}-{hashlib.sha256(relative_path.encode('utf-8')).hexdigest()[:8]}"


def _line_number(text: str, needle: str) -> int | None:
    position = text.casefold().find(needle.casefold())
    return None if position < 0 else text.count("\n", 0, position) + 1


class _ProfileBuilder:
    def __init__(
        self,
        project_id: str,
        discovery: DiscoveryResult,
        policy: ProjectCapabilityProfilerPolicy,
        manifest_roots: tuple[str, ...],
    ) -> None:
        self.project_id = project_id
        self.discovery = discovery
        self.policy = policy
        self.evidence: dict[str, dict[str, object]] = {}
        self.signals: dict[str, dict[str, object]] = {}
        self.module_manifests: dict[str, set[str]] = {".": set()}
        self.module_paths: dict[str, str] = {_module_id(project_id, "."): "."}
        self.manifest_roots = set(manifest_roots)
        self.sensitive_skipped = 0
        self.oversized_skipped = 0
        self.unreadable_skipped = 0
        self.invalid_skipped = 0
        self.inspection_budget_skipped = 0
        self.evidence_limit_skipped = 0
        self.inspected_files = 0
        self.inspected_bytes = 0

    def nearest_module_root(self, relative_path: str) -> str:
        parent = PurePosixPath(relative_path).parent
        candidates = [
            root
            for root in self.manifest_roots
            if root == "."
            or parent == PurePosixPath(root)
            or PurePosixPath(root) in parent.parents
        ]
        if not candidates:
            return "."
        return max(candidates, key=lambda item: len(PurePosixPath(item).parts))

    def inspect(self, root: Path, evidence: FileEvidence) -> str | None:
        if evidence.size > self.policy.maximum_inspected_file_bytes:
            self.oversized_skipped += 1
            return None
        if (
            self.inspected_files >= self.policy.maximum_inspected_files
            or self.inspected_bytes + evidence.size
            > self.policy.maximum_total_inspected_bytes
        ):
            self.inspection_budget_skipped += 1
            return None
        self.inspected_files += 1
        self.inspected_bytes += evidence.size
        try:
            text = _read_verified_text(root, evidence)
        except ProjectCapabilityProfileError as exc:
            if str(exc) in {
                "project capability evidence is not UTF-8",
                "project capability evidence is binary",
            }:
                self.unreadable_skipped += 1
                return None
            raise
        path_detectors = set(self.policy.sensitive_content_detectors) | {"email-address"}
        if detect_content_findings(
            text,
            evidence.relative_path,
            set(self.policy.sensitive_content_detectors),
        ) or detect_content_findings(
            evidence.relative_path,
            evidence.relative_path,
            path_detectors,
        ):
            self.sensitive_skipped += 1
            return None
        return text

    def add(
        self,
        capability_id: str,
        evidence: FileEvidence,
        *,
        marker_id: str,
        family: str,
        kind: str,
        confidence: float,
        module_root: str | None = None,
        line: int | None = None,
    ) -> str:
        definition = self.policy.capabilities.get(capability_id)
        if definition is None:
            raise ProjectCapabilityProfileError("profiler emitted an unknown capability")
        if confidence < self.policy.minimum_persisted_confidence:
            raise ProjectCapabilityProfileError("profiler emitted a below-threshold capability")
        relative_path = _safe_relative_path(evidence.relative_path, "capability evidence path")
        scope = _scope(relative_path)
        module = (
            module_root
            if module_root is not None
            else self.nearest_module_root(relative_path)
        )
        module_ref = _module_id(self.project_id, module)
        self.module_paths[module_ref] = module
        evidence_identity = {
            "marker_id": marker_id,
            "evidence_family": family,
            "kind": kind,
            "relative_path": relative_path,
            "file_digest": evidence.sha256,
            "scope": scope,
            **({"line_start": line, "line_end": line} if line is not None else {}),
        }
        evidence_id = f"evidence-{_digest(evidence_identity)}"
        if (
            evidence_id not in self.evidence
            and len(self.evidence) >= self.policy.maximum_evidence_items
        ):
            self.evidence_limit_skipped += 1
            return ""
        self.evidence[evidence_id] = {"evidence_id": evidence_id, **evidence_identity}
        key = f"{capability_id}:{module_ref}"
        signal = self.signals.setdefault(
            key,
            {
                "capability_id": capability_id,
                "name": definition.name,
                "confidence": confidence,
                "module_refs": {module_ref},
                "evidence_refs": set(),
                "families": set(),
            },
        )
        if signal["families"] and family not in signal["families"]:
            signal["confidence"] = round(
                1.0 - (1.0 - float(signal["confidence"])) * (1.0 - confidence),
                4,
            )
        else:
            signal["confidence"] = max(float(signal["confidence"]), confidence)
        signal["evidence_refs"].add(evidence_id)
        signal["families"].add(family)
        if PurePosixPath(relative_path).name.casefold() in MANIFEST_NAMES:
            self.module_manifests.setdefault(module, set()).add(evidence_id)
        return evidence_id


def _dependency_name(value: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.@/-]+)", value)
    return match.group(1).casefold().replace("_", "-") if match else ""


def _package_dependencies(payload: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, dict):
        raise ProjectCapabilityProfileError("package manifest root is invalid")
    runtime_dependencies = set()
    development_dependencies = set()
    for key in ("dependencies", "peerDependencies", "optionalDependencies", "devDependencies"):
        section = payload.get(key, {})
        if not isinstance(section, dict) or any(not isinstance(item, str) for item in section):
            raise ProjectCapabilityProfileError("package dependency section is invalid")
        target = development_dependencies if key == "devDependencies" else runtime_dependencies
        target.update(item.casefold() for item in section)
    return tuple(sorted(runtime_dependencies)), tuple(sorted(development_dependencies))


def _pom_dependencies(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise ProjectCapabilityProfileError("Maven manifest is invalid")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProjectCapabilityProfileError("Maven manifest is invalid") from exc
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"
    if root.tag.removeprefix(namespace) != "project":
        raise ProjectCapabilityProfileError("Maven manifest is invalid")
    runtime_values = set()
    test_values = set()
    for dependencies in root.findall(f"./{namespace}dependencies"):
        for dependency in dependencies.findall(f"./{namespace}dependency"):
            group = dependency.findtext(f"{namespace}groupId", "").strip().casefold()
            artifact = dependency.findtext(f"{namespace}artifactId", "").strip().casefold()
            scope = dependency.findtext(f"{namespace}scope", "compile").strip().casefold()
            optional = dependency.findtext(f"{namespace}optional", "false").strip().casefold()
            if not group or not artifact or optional == "true":
                continue
            coordinate = f"{group}:{artifact}"
            if scope == "test":
                test_values.add(coordinate)
            elif scope in {"", "compile", "provided", "runtime"}:
                runtime_values.add(coordinate)
    for plugin_group in (f"./{namespace}build/{namespace}plugins",):
        for plugins in root.findall(plugin_group):
            for plugin in plugins.findall(f"./{namespace}plugin"):
                group = plugin.findtext(f"{namespace}groupId", "").strip().casefold()
                artifact = plugin.findtext(f"{namespace}artifactId", "").strip().casefold()
                if group and artifact:
                    runtime_values.add(f"plugin:{group}:{artifact}")
    return tuple(sorted(runtime_values)), tuple(sorted(test_values))


def _pyproject_dependencies(
    payload: object,
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    if not isinstance(payload, dict):
        raise ProjectCapabilityProfileError("Python project manifest root is invalid")
    runtime_values = set()
    development_values = set()
    project = payload.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            runtime_values.update(
                _dependency_name(item) for item in dependencies if isinstance(item, str)
            )
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group_name, items in optional.items():
                if isinstance(items, list):
                    target = (
                        development_values
                        if any(
                            marker in str(group_name).casefold()
                            for marker in ("dev", "doc", "lint", "test")
                        )
                        else runtime_values
                    )
                    target.update(
                        _dependency_name(item)
                        for item in items
                        if isinstance(item, str)
                    )
    tool = payload.get("tool", {})
    if isinstance(tool, dict):
        poetry = tool.get("poetry", {})
        if isinstance(poetry, dict):
            for key in ("dependencies", "dev-dependencies"):
                section = poetry.get(key, {})
                if isinstance(section, dict):
                    target = (
                        development_values
                        if key == "dev-dependencies"
                        else runtime_values
                    )
                    target.update(
                        str(item).casefold().replace("_", "-") for item in section
                    )
        if "pytest" in tool:
            development_values.add("pytest")
        if "ruff" in tool:
            development_values.add("ruff")
    package_metadata = bool(
        isinstance(payload.get("project"), dict)
        or isinstance(payload.get("build-system"), dict)
        or (
            isinstance(tool, dict)
            and isinstance(tool.get("poetry"), dict)
            and bool(tool["poetry"].get("name"))
        )
    )
    return (
        tuple(sorted(item for item in runtime_values if item)),
        tuple(sorted(item for item in development_values if item)),
        package_metadata,
    )


def _detect_dependency_capabilities(names: tuple[str, ...], ecosystem: str) -> tuple[str, ...]:
    joined = "\n".join(names)
    found = set()
    if ecosystem == "node":
        mapping = {
            "react": "react",
            "next": "nextjs",
            "express": "express",
            "jest": "jest",
            "vitest": "vitest",
            "@playwright/test": "playwright",
            "cypress": "cypress",
            "eslint": "eslint",
            "oracledb": "oracle",
            "pg": "postgresql",
        }
        found.update(value for name, value in mapping.items() if name in names)
    elif ecosystem == "maven":
        coordinates = {
            tuple(item.removeprefix("plugin:").split(":", 1))
            for item in names
            if ":" in item.removeprefix("plugin:")
        }
        for group, artifact in coordinates:
            if group == "org.springframework.boot" or artifact.startswith("spring-boot-"):
                found.add("spring-boot")
            if artifact in {"spring-web", "spring-webmvc", "spring-webflux", "spring-boot-starter-web", "spring-boot-starter-webflux"}:
                found.add("spring-web")
            if artifact.startswith("spring-data-") or artifact.startswith("spring-boot-starter-data-"):
                found.add("spring-data")
            if group in {"junit", "org.junit.jupiter", "org.junit.vintage"} or artifact.startswith("junit-"):
                found.add("junit")
            if group.startswith("com.oracle.database") and artifact.startswith("ojdbc"):
                found.add("oracle")
            if group == "org.postgresql" and artifact == "postgresql":
                found.add("postgresql")
    else:
        mapping = {
            "fastapi": "fastapi",
            "flask": "flask",
            "django": "django",
            "pytest": "pytest",
            "ruff": "ruff",
            "oracledb": "oracle",
            "cx-oracle": "oracle",
            "psycopg": "postgresql",
            "psycopg2": "postgresql",
            "asyncpg": "postgresql",
        }
        found.update(value for name, value in mapping.items() if name in names)
    return tuple(sorted(found))


def _profile_manifest(
    builder: _ProfileBuilder,
    evidence: FileEvidence,
    text: str,
    policy: ProjectCapabilityProfilerPolicy,
) -> None:
    name = PurePosixPath(evidence.relative_path).name.casefold()
    module_root = _module_root(evidence.relative_path)
    if name == "package.json":
        try:
            runtime_dependencies, development_dependencies = _package_dependencies(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ProjectCapabilityProfileError("package manifest is invalid JSON") from exc
        builder.manifest_roots.add(module_root)
        builder.add("nodejs", evidence, marker_id="package-json", family="manifest", kind="manifest", confidence=0.9, module_root=module_root)
        builder.add("npm", evidence, marker_id="package-json-package-manager", family="manifest", kind="project-descriptor", confidence=0.85, module_root=module_root)
        for capability in _detect_dependency_capabilities(runtime_dependencies, "node"):
            line = next((_line_number(text, f'"{name}"') for name in runtime_dependencies if _detect_dependency_capabilities((name,), "node") == (capability,)), None)
            builder.add(capability, evidence, marker_id=f"node-dependency-{capability}", family="manifest", kind="manifest", confidence=0.9, module_root=module_root, line=line)
        for capability in _detect_dependency_capabilities(development_dependencies, "node"):
            if capability not in {"cypress", "eslint", "jest", "playwright", "vitest"}:
                continue
            line = next((_line_number(text, f'"{name}"') for name in development_dependencies if _detect_dependency_capabilities((name,), "node") == (capability,)), None)
            builder.add(capability, evidence, marker_id=f"node-dev-dependency-{capability}", family="manifest", kind="test-marker" if capability != "eslint" else "quality-marker", confidence=0.9, module_root=module_root, line=line)
    elif name == "pom.xml":
        runtime_dependencies, test_dependencies = _pom_dependencies(text)
        builder.manifest_roots.add(module_root)
        builder.add("java", evidence, marker_id="maven-project", family="manifest", kind="manifest", confidence=0.85, module_root=module_root)
        builder.add("maven", evidence, marker_id="maven-project-build", family="manifest", kind="project-descriptor", confidence=0.9, module_root=module_root)
        for capability in _detect_dependency_capabilities(runtime_dependencies, "maven"):
            builder.add(capability, evidence, marker_id=f"maven-dependency-{capability}", family="manifest", kind="manifest", confidence=0.9, module_root=module_root)
        for capability in _detect_dependency_capabilities(test_dependencies, "maven"):
            if capability != "junit":
                continue
            builder.add(capability, evidence, marker_id="maven-test-dependency-junit", family="manifest", kind="test-marker", confidence=0.9, module_root=module_root)
    elif name == "pyproject.toml":
        try:
            runtime_dependencies, development_dependencies, package_metadata = (
                _pyproject_dependencies(tomllib.loads(text))
            )
        except tomllib.TOMLDecodeError as exc:
            raise ProjectCapabilityProfileError("Python project manifest is invalid TOML") from exc
        builder.manifest_roots.add(module_root)
        builder.add("python", evidence, marker_id="python-project", family="manifest", kind="manifest", confidence=0.9, module_root=module_root)
        if package_metadata:
            builder.add("python-package", evidence, marker_id="python-project-build", family="manifest", kind="project-descriptor", confidence=0.85, module_root=module_root)
        for capability in _detect_dependency_capabilities(runtime_dependencies, "python"):
            builder.add(capability, evidence, marker_id=f"python-dependency-{capability}", family="manifest", kind="manifest", confidence=0.9, module_root=module_root)
        for capability in _detect_dependency_capabilities(development_dependencies, "python"):
            if capability not in {"pytest", "ruff"}:
                continue
            builder.add(capability, evidence, marker_id=f"python-dev-dependency-{capability}", family="manifest", kind="test-marker" if capability == "pytest" else "quality-marker", confidence=0.9, module_root=module_root)
    elif name in {"build.gradle", "build.gradle.kts"}:
        cleaned = re.sub(r"(?s)/\*.*?\*/|//[^\n]*", " ", text)
        runtime_dependency_lines = "\n".join(
            line
            for line in cleaned.splitlines()
            if re.match(
                r"\s*(?:api|implementation|runtimeOnly)\b",
                line,
            )
        ).casefold()
        test_dependency_lines = "\n".join(
            line
            for line in cleaned.splitlines()
            if re.match(r"\s*(?:testImplementation|testRuntimeOnly)\b", line)
        ).casefold()
        active_plugins = "\n".join(
            line
            for line in cleaned.splitlines()
            if re.search(r"\bid\s*\(?\s*['\"][^'\"]+['\"]", line)
            and not re.search(r"\bapply\s+false\b", line, re.IGNORECASE)
        ).casefold()
        builder.manifest_roots.add(module_root)
        if re.search(r"['\"](?:java|java-library)['\"]", active_plugins):
            builder.add("java", evidence, marker_id="gradle-java-plugin", family="manifest", kind="manifest", confidence=0.8, module_root=module_root)
        builder.add("gradle", evidence, marker_id="gradle-project-build", family="manifest", kind="project-descriptor", confidence=0.9, module_root=module_root)
        markers = {
            "spring-boot": ("org.springframework.boot",),
            "spring-web": ("spring-boot-starter-web", "spring-webmvc"),
            "spring-data": ("spring-data", "spring-boot-starter-data"),
            "junit": ("junit", "jupiter"),
            "oracle": ("ojdbc",),
            "postgresql": ("org.postgresql",),
        }
        for capability, needles in markers.items():
            search_space = (
                active_plugins
                if capability == "spring-boot"
                else f"{runtime_dependency_lines}\n{test_dependency_lines}"
                if capability == "junit"
                else runtime_dependency_lines
            )
            needle = next((item for item in needles if item in search_space), None)
            if needle:
                builder.add(capability, evidence, marker_id=f"gradle-marker-{capability}", family="manifest", kind="manifest", confidence=0.8, module_root=module_root, line=_line_number(text, needle))


def _path_capabilities(builder: _ProfileBuilder, evidence: FileEvidence) -> None:
    path = PurePosixPath(evidence.relative_path)
    name = path.name.casefold()
    lowered = evidence.relative_path.casefold()
    scope = _scope(evidence.relative_path)
    production_marker = scope in {"production", "migration"}
    delivery_marker = scope in {"production", "migration", "ci"}
    if production_marker and name == "go.mod":
        builder.add("go", evidence, marker_id="go-module", family="path", kind="project-descriptor", confidence=0.85)
    if production_marker and name == "cargo.toml":
        builder.add("rust", evidence, marker_id="cargo-project", family="path", kind="project-descriptor", confidence=0.85)
    if production_marker and path.suffix.casefold() in {".csproj", ".sln"}:
        builder.add("dotnet", evidence, marker_id="dotnet-project", family="path", kind="project-descriptor", confidence=0.85)
    if delivery_marker and (name == "dockerfile" or name.startswith("dockerfile.")):
        builder.add("container", evidence, marker_id="dockerfile", family="container", kind="container", confidence=0.85)
    if delivery_marker and name in {"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"}:
        builder.add("container-compose", evidence, marker_id="container-compose", family="container", kind="container", confidence=0.85)
    if lowered.startswith(".github/workflows/") and path.suffix.casefold() in {".yml", ".yaml"}:
        builder.add("github-actions", evidence, marker_id="github-actions-workflow", family="pipeline", kind="pipeline", confidence=0.9)
    if delivery_marker and name == ".gitlab-ci.yml":
        builder.add("gitlab-ci", evidence, marker_id="gitlab-ci", family="pipeline", kind="pipeline", confidence=0.9)
    if delivery_marker and name == "jenkinsfile":
        builder.add("jenkins", evidence, marker_id="jenkinsfile", family="pipeline", kind="pipeline", confidence=0.9)
    if delivery_marker and name == "azure-pipelines.yml":
        builder.add("azure-pipelines", evidence, marker_id="azure-pipelines", family="pipeline", kind="pipeline", confidence=0.9)
    if delivery_marker and name == "bitbucket-pipelines.yml":
        builder.add("bitbucket-pipelines", evidence, marker_id="bitbucket-pipelines", family="pipeline", kind="pipeline", confidence=0.9)
    if delivery_marker and name in {"chart.yaml", "kustomization.yaml"}:
        builder.add("kubernetes", evidence, marker_id="kubernetes-descriptor", family="container", kind="container", confidence=0.85)
    if name in {"pytest.ini", "conftest.py"}:
        builder.add("pytest", evidence, marker_id="pytest-marker", family="path", kind="test-marker", confidence=0.8)
    if name in {"jest.config.js", "jest.config.cjs", "jest.config.mjs", "jest.config.ts"}:
        builder.add("jest", evidence, marker_id="jest-config", family="path", kind="test-marker", confidence=0.8)
    if name.startswith("vitest.config."):
        builder.add("vitest", evidence, marker_id="vitest-config", family="path", kind="test-marker", confidence=0.8)
    if name.startswith("playwright.config."):
        builder.add("playwright", evidence, marker_id="playwright-config", family="path", kind="test-marker", confidence=0.8)
    if name.startswith("cypress.config."):
        builder.add("cypress", evidence, marker_id="cypress-config", family="path", kind="test-marker", confidence=0.8)
    if (
        _scope(evidence.relative_path) in {"production", "migration"}
        and path.suffix.casefold() in {".pks", ".pkb", ".pls", ".plb", ".tps", ".tpb"}
    ):
        builder.add("plsql", evidence, marker_id="plsql-file-extension", family="path", kind="database-marker", confidence=0.8)
        builder.add("oracle", evidence, marker_id="oracle-plsql-file", family="path", kind="database-marker", confidence=0.8)
    if _scope(evidence.relative_path) == "migration" and path.suffix.casefold() in SQL_SUFFIXES:
        builder.add("data-migration", evidence, marker_id="migration-sql-file", family="path", kind="database-marker", confidence=0.8)


def _profile_sql(builder: _ProfileBuilder, evidence: FileEvidence, text: str) -> None:
    ut_annotations = re.findall(r"(?im)^\s*--%(?:suite|test)\b", text)
    without_literals = re.sub(r"'(?:''|[^'])*'", "''", text)
    normalized = re.sub(
        r"(?s)/\*.*?\*/|--[^\n]*",
        " ",
        without_literals,
    ).casefold()
    source_scope = _scope(evidence.relative_path)
    oracle_markers = {
        "plsql": ("create or replace package", "create or replace procedure", "create or replace function", "package body", "type body"),
        "oracle-metadata": ("dbms_metadata.get_ddl", "dbms_metadata.open", "all_dependencies", "user_dependencies", "dba_dependencies"),
        "utplsql": ("ut.expect", "ut.run"),
    }
    if ut_annotations:
        builder.add(
            "utplsql",
            evidence,
            marker_id="sql-marker-utplsql",
            family="sql-marker",
            kind="test-marker",
            confidence=0.8,
            line=_line_number(text, ut_annotations[0]),
        )
    for capability, needles in oracle_markers.items():
        if capability != "utplsql" and source_scope not in {"production", "migration"}:
            continue
        needle = next((item for item in needles if item in normalized), None)
        if needle:
            builder.add(capability, evidence, marker_id=f"sql-marker-{capability}", family="sql-marker", kind="database-marker" if capability != "utplsql" else "test-marker", confidence=0.8, line=_line_number(text, needle))
            if capability in {"plsql", "oracle-metadata"}:
                builder.add("oracle", evidence, marker_id=f"oracle-{capability}", family="sql-marker", kind="database-marker", confidence=0.8, line=_line_number(text, needle))
    if source_scope not in {"production", "migration"}:
        return
    postgres_markers = ("language plpgsql", "create extension", "pg_catalog", "do $$")
    postgres_hits = [item for item in postgres_markers if item in normalized]
    if len(postgres_hits) >= 1:
        builder.add("postgresql", evidence, marker_id="postgresql-sql-dialect", family="sql-marker", kind="database-marker", confidence=0.8, line=_line_number(text, postgres_hits[0]))


def _augment_architecture(builder: _ProfileBuilder) -> None:
    by_module: dict[str, set[str]] = {}
    first_evidence: dict[tuple[str, str], str] = {}
    for signal in builder.signals.values():
        capability_id = str(signal["capability_id"])
        module_ref = next(iter(signal["module_refs"]))
        by_module.setdefault(module_ref, set()).add(capability_id)
        first_evidence[(module_ref, capability_id)] = sorted(signal["evidence_refs"])[0]

    def derived(capability_id: str, module_ref: str, requirements: tuple[str, ...]) -> None:
        refs = [first_evidence[(module_ref, item)] for item in requirements if (module_ref, item) in first_evidence]
        if not refs:
            return
        source = builder.evidence[refs[0]]
        file_evidence = next(item for item in builder.discovery.files if item.relative_path == source["relative_path"])
        builder.add(
            capability_id,
            file_evidence,
            marker_id=f"derived-{capability_id}",
            family="structure",
            kind="source-structure",
            confidence=0.8,
            module_root=builder.module_paths[module_ref],
        )

    frontend_markers = {"react", "nextjs"}
    backend_markers = {"spring-boot", "spring-web", "express", "fastapi", "flask", "django"}
    for module_ref, capabilities in tuple(by_module.items()):
        if capabilities.intersection(frontend_markers):
            derived("frontend", module_ref, tuple(sorted(capabilities.intersection(frontend_markers))))
        if capabilities.intersection(backend_markers):
            derived("backend", module_ref, tuple(sorted(capabilities.intersection(backend_markers))))
        if capabilities.intersection({"plsql", "oracle-metadata"}):
            derived("database-development", module_ref, tuple(sorted(capabilities.intersection({"plsql", "oracle-metadata"}))))
        testing = capabilities.intersection({"cypress", "jest", "junit", "playwright", "pytest", "utplsql", "vitest"})
        if testing:
            derived("automated-tests", module_ref, tuple(sorted(testing)))
    all_capabilities = {str(signal["capability_id"]) for signal in builder.signals.values()}
    if "frontend" in all_capabilities and "backend" in all_capabilities:
        frontend_signal = next(signal for signal in builder.signals.values() if signal["capability_id"] == "frontend")
        backend_signal = next(signal for signal in builder.signals.values() if signal["capability_id"] == "backend")
        evidence_id = sorted(frontend_signal["evidence_refs"])[0]
        source = builder.evidence[evidence_id]
        file_evidence = next(item for item in builder.discovery.files if item.relative_path == source["relative_path"])
        builder.add("full-stack", file_evidence, marker_id="derived-full-stack", family="structure", kind="source-structure", confidence=0.8, module_root=".")
        backend_evidence_id = sorted(backend_signal["evidence_refs"])[0]
        backend_source = builder.evidence[backend_evidence_id]
        backend_file = next(item for item in builder.discovery.files if item.relative_path == backend_source["relative_path"])
        builder.add("full-stack", backend_file, marker_id="derived-full-stack-backend", family="structure", kind="source-structure", confidence=0.8, module_root=".")
    non_empty_manifest_roots = [root for root, refs in builder.module_manifests.items() if refs]
    if len(non_empty_manifest_roots) > 1:
        manifest_refs = sorted(ref for refs in builder.module_manifests.values() for ref in refs)
        if manifest_refs:
            source = builder.evidence[manifest_refs[0]]
            file_evidence = next(item for item in builder.discovery.files if item.relative_path == source["relative_path"])
            builder.add("multi-module", file_evidence, marker_id="derived-multi-module", family="structure", kind="source-structure", confidence=0.8, module_root=".")


def _is_path_marker_candidate(evidence: FileEvidence) -> bool:
    path = PurePosixPath(evidence.relative_path)
    name = path.name.casefold()
    lowered = evidence.relative_path.casefold()
    return bool(
        name in {
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            "bitbucket-pipelines.yml",
            "cargo.toml",
            "chart.yaml",
            "compose.yaml",
            "compose.yml",
            "conftest.py",
            "docker-compose.yaml",
            "docker-compose.yml",
            "go.mod",
            "jenkinsfile",
            "kustomization.yaml",
            "openapi.json",
            "openapi.yaml",
            "openapi.yml",
            "pytest.ini",
            "swagger.json",
            "swagger.yaml",
            "swagger.yml",
        }
        or name == "dockerfile"
        or name.startswith("dockerfile.")
        or name.startswith(("cypress.config.", "jest.config.", "playwright.config.", "vitest.config."))
        or lowered.startswith(".github/workflows/")
        or path.suffix.casefold() in {".csproj", ".graphql", ".proto", ".sln", *SQL_SUFFIXES}
    )


def _profile_interface(
    builder: _ProfileBuilder,
    evidence: FileEvidence,
    text: str,
) -> None:
    if _scope(evidence.relative_path) not in {"production", "migration"}:
        return
    path = PurePosixPath(evidence.relative_path)
    name = path.name.casefold()
    marker = None
    if name in {"openapi.json", "swagger.json"}:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict) and (
            isinstance(payload.get("openapi"), str)
            or isinstance(payload.get("swagger"), str)
        ):
            marker = "openapi-document"
    elif name in {"openapi.yaml", "openapi.yml", "swagger.yaml", "swagger.yml"}:
        if re.search(r"(?m)^\s*(?:openapi|swagger)\s*:\s*['\"]?[0-9]", text):
            marker = "openapi-document"
    elif path.suffix.casefold() == ".graphql":
        if re.search(r"(?m)^\s*type\s+Query\b", re.sub(r"#[^\n]*", "", text)):
            marker = "graphql-query-schema"
    elif path.suffix.casefold() == ".proto":
        if re.search(r"(?m)^\s*service\s+[A-Za-z_][A-Za-z0-9_]*\s*\{", re.sub(r"//[^\n]*", "", text)):
            marker = "grpc-service"
    if marker is not None:
        builder.add(
            "api",
            evidence,
            marker_id=marker,
            family="manifest",
            kind="project-descriptor",
            confidence=0.8,
        )


def build_project_capability_profile(
    repo_root: Path,
    source_root: Path,
    project_id: str,
    binding: SourceBinding,
    discovery: DiscoveryResult,
) -> dict[str, object]:
    """Build a deterministic profile while retaining no inspected source content."""

    if not IDENTIFIER.fullmatch(project_id):
        raise ProjectCapabilityProfileError("project capability profile project id is invalid")
    if source_root.is_symlink():
        raise ProjectCapabilityProfileError("project capability source root is unsafe")
    root = source_root.resolve(strict=True)
    if not root.is_dir():
        raise ProjectCapabilityProfileError("project capability source root is unsafe")
    locator_path = Path(binding.locator.value)
    if (
        discovery.binding_id != binding.binding_id
        or discovery.binding_revision != binding.revision
        or project_id != binding.source_id
        or project_id != discovery.source_id
        or binding.source_kind != "project"
        or binding.default_access != "read-only"
        or "read" not in binding.capabilities
        or "metadata" not in binding.capabilities
        or "write" in binding.capabilities
        or binding.locator.kind != "local-path"
        or locator_path.is_symlink()
        or locator_path.resolve(strict=True) != root
    ):
        raise ProjectCapabilityProfileError("project capability discovery binding is stale")
    policy = load_project_capability_profiler_policy(repo_root)
    builder = _ProfileBuilder(project_id, discovery, policy, ())
    for evidence in sorted(
        discovery.files,
        key=lambda item: (
            not (
                PurePosixPath(item.relative_path).name.casefold() in MANIFEST_NAMES
                and _scope(item.relative_path) in {"production", "migration"}
            ),
            item.relative_path,
        ),
    ):
        name = PurePosixPath(evidence.relative_path).name.casefold()
        is_manifest = name in MANIFEST_NAMES and _scope(evidence.relative_path) in {"production", "migration"}
        is_sql = PurePosixPath(evidence.relative_path).suffix.casefold() in SQL_SUFFIXES
        is_path_marker = _is_path_marker_candidate(evidence)
        if not (is_manifest or is_sql or is_path_marker):
            continue
        text = builder.inspect(root, evidence)
        if text is None:
            continue
        if is_path_marker:
            _path_capabilities(builder, evidence)
            _profile_interface(builder, evidence, text)
        if is_manifest:
            try:
                _profile_manifest(builder, evidence, text, policy)
            except ProjectCapabilityProfileError as exc:
                if str(exc) in {
                    "package manifest is invalid JSON",
                    "package manifest root is invalid",
                    "package dependency section is invalid",
                    "Maven manifest is invalid",
                    "Python project manifest is invalid TOML",
                    "Python project manifest root is invalid",
                }:
                    builder.invalid_skipped += 1
                    continue
                raise
        if is_sql:
            _profile_sql(builder, evidence, text)
    _augment_architecture(builder)
    evidence_catalog = tuple(builder.evidence[item] for item in sorted(builder.evidence))
    dimensions: dict[str, list[dict[str, object]]] = {category: [] for category in CATEGORIES}
    for key in sorted(builder.signals):
        signal = builder.signals[key]
        capability_id = str(signal["capability_id"])
        definition = policy.capabilities[capability_id]
        confidence = round(float(signal["confidence"]), 4)
        band = (
            "confirmed"
            if confidence >= policy.confidence_bands["confirmed"]
            else "high"
            if confidence >= policy.confidence_bands["high"]
            else "medium"
        )
        dimensions[definition.category].append(
            {
                "capability_id": capability_id,
                "name": definition.name,
                "confidence": confidence,
                "confidence_band": band,
                "detection_method": (
                    "multi-signal-inference"
                    if len(signal["families"]) > 1
                    else "structural-inference"
                    if "structure" in signal["families"]
                    else "explicit-marker"
                ),
                "module_refs": sorted(signal["module_refs"]),
                "evidence_refs": sorted(signal["evidence_refs"]),
            }
        )
    for values in dimensions.values():
        values.sort(key=lambda item: (str(item["capability_id"]), tuple(item["module_refs"])))
    capability_ids = sorted({str(signal["capability_id"]) for signal in builder.signals.values()})
    modules = []
    module_roots = set(builder.module_paths.values()) | set(builder.module_manifests) | {"."}
    for relative in sorted(module_roots):
        modules.append(
            {
                "module_id": _module_id(project_id, relative),
                "relative_path": relative,
                "manifest_evidence_refs": sorted(builder.module_manifests.get(relative, set())),
            }
        )
    module_ids = [str(item["module_id"]) for item in modules]
    workloads = []
    for definition in policy.workloads:
        triggers = tuple(item for item in definition.trigger_capabilities if item in capability_ids)
        if definition.trigger_capabilities and not triggers:
            continue
        required = list(triggers if definition.trigger_capabilities else capability_ids)
        matching_signals = [
            signal
            for signal in builder.signals.values()
            if signal["capability_id"] in required
        ]
        refs = sorted(
            {
                ref
                for signal in matching_signals
                for ref in signal["evidence_refs"]
            }
        )
        workload_scopes = (
            sorted(
                {
                    module_ref
                    for signal in matching_signals
                    for module_ref in signal["module_refs"]
                }
            )
            if definition.trigger_capabilities
            else module_ids
        )
        semantic = {
            "workload_id": definition.workload_id,
            "workload_kind": definition.workload_kind,
            "trust_role": definition.trust_role,
            "specialization_profile_id": definition.specialization_profile_id,
            "scope_refs": workload_scopes,
            "required_capability_refs": required,
            "context_evidence_refs": refs,
            "benchmark_dimensions": list(definition.benchmark_dimensions),
            "evaluation_traits": list(definition.evaluation_traits),
            "fixture_policy": definition.fixture_policy,
        }
        workloads.append({**semantic, "workload_digest": _digest(semantic)})
    workloads.sort(key=lambda item: str(item["workload_id"]))
    limitations = {
        "discovery_skipped": sum(int(value) for value in discovery.skipped.values()),
        "sensitive_content_skipped": builder.sensitive_skipped,
        "oversized_content_skipped": builder.oversized_skipped,
        "unreadable_content_skipped": builder.unreadable_skipped,
        "invalid_content_skipped": builder.invalid_skipped,
        "inspection_budget_skipped": builder.inspection_budget_skipped,
        "evidence_limit_skipped": builder.evidence_limit_skipped,
    }
    coverage_state = (
        "partial-safe"
        if any(
            limitations[key] > 0
            for key in (
                "sensitive_content_skipped",
                "oversized_content_skipped",
                "unreadable_content_skipped",
                "invalid_content_skipped",
                "inspection_budget_skipped",
                "evidence_limit_skipped",
            )
        )
        else "complete"
    )
    authoritative_for_model_assignment = coverage_state == "complete"
    evidence_digest = _digest(evidence_catalog)
    capability_digest = _digest(
        {
            "modules": modules,
            "dimensions": dimensions,
            "workload_profiles": workloads,
            "limitations": limitations,
            "coverage_state": coverage_state,
            "authoritative_for_model_assignment": authoritative_for_model_assignment,
        }
    )
    profile_identity = {
        "schema_version": 1,
        "project_id": project_id,
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "source_digest": discovery.root_digest,
        "profiler_id": policy.profiler_id,
        "profiler_revision": policy.profiler_revision,
        "policy_digest": policy.policy_digest,
        "evidence_digest": evidence_digest,
        "capability_digest": capability_digest,
    }
    payload = {
        "schema_ref": "schemas/project-capability-profile.schema.json",
        "schema_version": 1,
        "project_id": project_id,
        "profile_revision": 1,
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "source_digest": discovery.root_digest,
        "profiler": {
            "profiler_id": policy.profiler_id,
            "profiler_revision": policy.profiler_revision,
            "policy_digest": policy.policy_digest,
        },
        "modules": modules,
        "evidence_catalog": list(evidence_catalog),
        "dimensions": dimensions,
        "workload_profiles": workloads,
        "limitations": limitations,
        "coverage_state": coverage_state,
        "authoritative_for_model_assignment": authoritative_for_model_assignment,
        "evidence_digest": evidence_digest,
        "capability_digest": capability_digest,
        "profile_digest": _digest(profile_identity),
        "invariants": {
            "source_content_included": False,
            "sensitive_values_included": False,
            "absolute_paths_included": False,
            "network_effect_performed": False,
            "grants_authority": False,
        },
    }
    return parse_project_capability_profile(
        payload,
        discovery=discovery,
        policy=policy,
    )


def parse_project_capability_profile(
    payload: object,
    *,
    discovery: DiscoveryResult | None = None,
    policy: ProjectCapabilityProfilerPolicy | None = None,
) -> dict[str, object]:
    """Validate a persisted profile, all internal references, and its digests."""

    expected = {
        "schema_ref",
        "schema_version",
        "project_id",
        "profile_revision",
        "binding_id",
        "binding_revision",
        "source_digest",
        "profiler",
        "modules",
        "evidence_catalog",
        "dimensions",
        "workload_profiles",
        "limitations",
        "coverage_state",
        "authoritative_for_model_assignment",
        "evidence_digest",
        "capability_digest",
        "profile_digest",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ProjectCapabilityProfileError("project capability profile fields are invalid")
    if payload.get("schema_ref") != "schemas/project-capability-profile.schema.json" or payload.get("schema_version") != 1:
        raise ProjectCapabilityProfileError("project capability profile schema is invalid")
    project_id = payload.get("project_id")
    binding_id = payload.get("binding_id")
    binding_revision = payload.get("binding_revision")
    source_digest = payload.get("source_digest")
    profile_revision = payload.get("profile_revision")
    if (
        not isinstance(project_id, str)
        or not IDENTIFIER.fullmatch(project_id)
        or not isinstance(binding_id, str)
        or not IDENTIFIER.fullmatch(binding_id)
        or not isinstance(binding_revision, int)
        or isinstance(binding_revision, bool)
        or binding_revision < 1
        or not isinstance(profile_revision, int)
        or isinstance(profile_revision, bool)
        or profile_revision < 1
        or not isinstance(source_digest, str)
        or not SHA256.fullmatch(source_digest)
    ):
        raise ProjectCapabilityProfileError("project capability profile identity is invalid")
    profiler = payload.get("profiler")
    if not isinstance(profiler, dict) or set(profiler) != {"profiler_id", "profiler_revision", "policy_digest"}:
        raise ProjectCapabilityProfileError("project capability profiler identity is invalid")
    if (
        not isinstance(profiler.get("profiler_id"), str)
        or not IDENTIFIER.fullmatch(str(profiler["profiler_id"]))
        or not isinstance(profiler.get("profiler_revision"), int)
        or isinstance(profiler.get("profiler_revision"), bool)
        or int(profiler["profiler_revision"]) < 1
        or not isinstance(profiler.get("policy_digest"), str)
        or not SHA256.fullmatch(str(profiler["policy_digest"]))
    ):
        raise ProjectCapabilityProfileError("project capability profiler values are invalid")
    evidence_payload = payload.get("evidence_catalog")
    if not isinstance(evidence_payload, list):
        raise ProjectCapabilityProfileError("project capability evidence catalog is invalid")
    evidence_ids = set()
    evidence_paths: dict[str, str] = {}
    discovery_files = {item.relative_path: item for item in discovery.files} if discovery else {}
    for item in evidence_payload:
        required = {"evidence_id", "marker_id", "evidence_family", "kind", "relative_path", "file_digest", "scope"}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - required - {"line_start", "line_end"}:
            raise ProjectCapabilityProfileError("project capability evidence item is invalid")
        evidence_id = item.get("evidence_id")
        marker_id = item.get("marker_id")
        relative_path = _safe_relative_path(item.get("relative_path"), "capability evidence path")
        file_digest = item.get("file_digest")
        semantic = {key: value for key, value in item.items() if key != "evidence_id"}
        if (
            not isinstance(evidence_id, str)
            or not EVIDENCE_ID.fullmatch(evidence_id)
            or evidence_id != f"evidence-{_digest(semantic)}"
            or evidence_id in evidence_ids
            or not isinstance(marker_id, str)
            or not IDENTIFIER.fullmatch(marker_id)
            or item.get("evidence_family") not in {"manifest", "path", "source-marker", "sql-marker", "pipeline", "container", "structure"}
            or item.get("kind") not in {"manifest", "project-descriptor", "test-marker", "pipeline", "container", "database-marker", "quality-marker", "source-structure"}
            or item.get("scope") not in {"production", "test", "migration", "ci", "example", "fixture", "documentation"}
            or not isinstance(file_digest, str)
            or not SHA256.fullmatch(file_digest)
        ):
            raise ProjectCapabilityProfileError("project capability evidence values are invalid")
        line_start = item.get("line_start")
        line_end = item.get("line_end")
        if (line_start is None) != (line_end is None) or (
            line_start is not None
            and (
                not isinstance(line_start, int)
                or isinstance(line_start, bool)
                or not isinstance(line_end, int)
                or isinstance(line_end, bool)
                or line_start < 1
                or line_end < line_start
            )
        ):
            raise ProjectCapabilityProfileError("project capability evidence line range is invalid")
        if discovery is not None:
            current = discovery_files.get(relative_path)
            if current is None or current.sha256 != file_digest:
                raise ProjectCapabilityProfileError("project capability evidence does not match discovery")
        evidence_ids.add(evidence_id)
        evidence_paths[evidence_id] = relative_path
    if tuple(item["evidence_id"] for item in evidence_payload) != tuple(sorted(evidence_ids)):
        raise ProjectCapabilityProfileError("project capability evidence must be sorted")
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ProjectCapabilityProfileError("project capability modules are invalid")
    module_ids = set()
    module_paths = set()
    previous_module_path = None
    for item in modules:
        if not isinstance(item, dict) or set(item) != {"module_id", "relative_path", "manifest_evidence_refs"}:
            raise ProjectCapabilityProfileError("project capability module is invalid")
        module_id = item.get("module_id")
        if not isinstance(module_id, str) or not IDENTIFIER.fullmatch(module_id) or module_id in module_ids:
            raise ProjectCapabilityProfileError("project capability module id is invalid")
        _safe_relative_path(item.get("relative_path"), "module path")
        relative_path = str(item["relative_path"])
        if relative_path in module_paths or (
            previous_module_path is not None and relative_path < previous_module_path
        ):
            raise ProjectCapabilityProfileError("project capability modules must be unique and sorted")
        expected_module_id = _module_id(str(project_id), relative_path)
        if module_id != expected_module_id:
            raise ProjectCapabilityProfileError("project capability module identity is invalid")
        refs = _identifier_list(item.get("manifest_evidence_refs"), "module evidence refs")
        if any(ref not in evidence_ids for ref in refs):
            raise ProjectCapabilityProfileError("project capability module has orphan evidence")
        module_ids.add(module_id)
        module_paths.add(relative_path)
        previous_module_path = relative_path
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(CATEGORIES):
        raise ProjectCapabilityProfileError("project capability dimensions are invalid")
    capability_ids = set()
    capability_evidence: dict[str, set[str]] = {}
    referenced_evidence: set[str] = set()
    for category, signals in dimensions.items():
        if not isinstance(signals, list):
            raise ProjectCapabilityProfileError("project capability dimension signals are invalid")
        previous = None
        for signal in signals:
            expected_signal = {"capability_id", "name", "confidence", "confidence_band", "detection_method", "module_refs", "evidence_refs"}
            if not isinstance(signal, dict) or set(signal) != expected_signal:
                raise ProjectCapabilityProfileError("project capability signal is invalid")
            capability_id = signal.get("capability_id")
            confidence = signal.get("confidence")
            key = (str(capability_id), tuple(signal.get("module_refs", [])))
            if previous is not None and key < previous:
                raise ProjectCapabilityProfileError("project capability signals must be sorted")
            previous = key
            if (
                not isinstance(capability_id, str)
                or not IDENTIFIER.fullmatch(capability_id)
                or not isinstance(signal.get("name"), str)
                or not signal.get("name")
                or not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0 <= float(confidence) <= 1
                or signal.get("confidence_band") not in {"medium", "high", "confirmed"}
                or signal.get("detection_method") not in {"explicit-marker", "structural-inference", "multi-signal-inference"}
            ):
                raise ProjectCapabilityProfileError("project capability signal values are invalid")
            if policy is not None:
                definition = policy.capabilities.get(capability_id)
                expected_band = (
                    "confirmed"
                    if float(confidence) >= policy.confidence_bands["confirmed"]
                    else "high"
                    if float(confidence) >= policy.confidence_bands["high"]
                    else "medium"
                )
                if (
                    definition is None
                    or definition.category != category
                    or definition.name != signal["name"]
                    or float(confidence) < policy.minimum_persisted_confidence
                    or signal["confidence_band"] != expected_band
                ):
                    raise ProjectCapabilityProfileError("project capability signal conflicts with policy")
            refs = _identifier_list(signal.get("evidence_refs"), "signal evidence refs", allow_empty=False)
            scopes = _identifier_list(signal.get("module_refs"), "signal module refs", allow_empty=False)
            if any(ref not in evidence_ids for ref in refs) or any(ref not in module_ids for ref in scopes):
                raise ProjectCapabilityProfileError("project capability signal has orphan references")
            capability_ids.add(capability_id)
            capability_evidence.setdefault(capability_id, set()).update(refs)
            referenced_evidence.update(refs)
    workloads = payload.get("workload_profiles")
    if not isinstance(workloads, list):
        raise ProjectCapabilityProfileError("project workload profiles are invalid")
    workload_ids = set()
    for item in workloads:
        semantic_fields = {"workload_id", "workload_kind", "trust_role", "specialization_profile_id", "scope_refs", "required_capability_refs", "context_evidence_refs", "benchmark_dimensions", "evaluation_traits", "fixture_policy"}
        if not isinstance(item, dict) or set(item) != semantic_fields | {"workload_digest"}:
            raise ProjectCapabilityProfileError("project workload profile is invalid")
        workload_id = item.get("workload_id")
        if (
            not isinstance(workload_id, str)
            or not IDENTIFIER.fullmatch(workload_id)
            or workload_id in workload_ids
            or item.get("workload_kind") not in WORKLOAD_KINDS
            or item.get("trust_role") not in TRUST_ROLES
            or not isinstance(item.get("specialization_profile_id"), str)
            or not IDENTIFIER.fullmatch(str(item["specialization_profile_id"]))
            or item.get("fixture_policy") not in FIXTURE_POLICIES
            or not isinstance(item.get("workload_digest"), str)
            or item["workload_digest"] != _digest({key: item[key] for key in semantic_fields})
        ):
            raise ProjectCapabilityProfileError("project workload profile values are invalid")
        if policy is not None:
            definition = next(
                (
                    candidate
                    for candidate in policy.workloads
                    if candidate.workload_id == workload_id
                ),
                None,
            )
            if (
                definition is None
                or item["workload_kind"] != definition.workload_kind
                or item["trust_role"] != definition.trust_role
                or item["specialization_profile_id"]
                != definition.specialization_profile_id
                or item["fixture_policy"] != definition.fixture_policy
                or tuple(item["benchmark_dimensions"])
                != definition.benchmark_dimensions
                or tuple(item["evaluation_traits"])
                != definition.evaluation_traits
            ):
                raise ProjectCapabilityProfileError("project workload profile conflicts with policy")
        scopes = _identifier_list(item.get("scope_refs"), "workload scopes", allow_empty=False)
        required = _identifier_list(item.get("required_capability_refs"), "workload capabilities")
        refs = _identifier_list(item.get("context_evidence_refs"), "workload evidence refs")
        _identifier_list(item.get("benchmark_dimensions"), "workload benchmark dimensions", allow_empty=False)
        _identifier_list(item.get("evaluation_traits"), "workload evaluation traits", allow_empty=False)
        if any(ref not in module_ids for ref in scopes) or any(ref not in capability_ids for ref in required) or any(ref not in evidence_ids for ref in refs):
            raise ProjectCapabilityProfileError("project workload profile has orphan references")
        expected_context = sorted(
            {
                ref
                for capability_id in required
                for ref in capability_evidence.get(capability_id, set())
            }
        )
        if list(refs) != expected_context:
            raise ProjectCapabilityProfileError("project workload evidence conflicts with capabilities")
        referenced_evidence.update(refs)
        workload_ids.add(workload_id)
    if tuple(item["workload_id"] for item in workloads) != tuple(sorted(workload_ids)):
        raise ProjectCapabilityProfileError("project workload profiles must be sorted")
    for module in modules:
        referenced_evidence.update(module["manifest_evidence_refs"])
    if evidence_ids != referenced_evidence:
        raise ProjectCapabilityProfileError("project capability evidence must be reachable")
    limitations = payload.get("limitations")
    if (
        not isinstance(limitations, dict)
        or set(limitations) != {
            "discovery_skipped",
            "sensitive_content_skipped",
            "oversized_content_skipped",
            "unreadable_content_skipped",
            "invalid_content_skipped",
            "inspection_budget_skipped",
            "evidence_limit_skipped",
        }
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in limitations.values())
    ):
        raise ProjectCapabilityProfileError("project capability limitations are invalid")
    expected_coverage_state = (
        "partial-safe"
        if any(
            limitations[key] > 0
            for key in (
                "sensitive_content_skipped",
                "oversized_content_skipped",
                "unreadable_content_skipped",
                "invalid_content_skipped",
                "inspection_budget_skipped",
                "evidence_limit_skipped",
            )
        )
        else "complete"
    )
    if (
        payload.get("coverage_state") != expected_coverage_state
        or payload.get("authoritative_for_model_assignment")
        is not (expected_coverage_state == "complete")
    ):
        raise ProjectCapabilityProfileError("project capability coverage is invalid")
    if payload.get("invariants") != {
        "source_content_included": False,
        "sensitive_values_included": False,
        "absolute_paths_included": False,
        "network_effect_performed": False,
        "grants_authority": False,
    }:
        raise ProjectCapabilityProfileError("project capability invariants are invalid")
    evidence_digest = _digest(evidence_payload)
    capability_digest = _digest(
        {
            "modules": modules,
            "dimensions": dimensions,
            "workload_profiles": workloads,
            "limitations": limitations,
            "coverage_state": payload["coverage_state"],
            "authoritative_for_model_assignment": payload[
                "authoritative_for_model_assignment"
            ],
        }
    )
    profile_identity = {
        "schema_version": 1,
        "project_id": project_id,
        "binding_id": binding_id,
        "binding_revision": binding_revision,
        "source_digest": source_digest,
        "profiler_id": profiler["profiler_id"],
        "profiler_revision": profiler["profiler_revision"],
        "policy_digest": profiler["policy_digest"],
        "evidence_digest": evidence_digest,
        "capability_digest": capability_digest,
    }
    if (
        payload.get("evidence_digest") != evidence_digest
        or payload.get("capability_digest") != capability_digest
        or payload.get("profile_digest") != _digest(profile_identity)
    ):
        raise ProjectCapabilityProfileError("project capability profile digest is invalid")
    if discovery is not None and (
        discovery.binding_id != binding_id
        or discovery.binding_revision != binding_revision
        or discovery.root_digest != source_digest
    ):
        raise ProjectCapabilityProfileError("project capability profile is stale")
    return json.loads(json.dumps(payload, ensure_ascii=False))


def project_capability_profile_is_current(
    repo_root: Path,
    payload: object,
    project_id: str,
    binding: SourceBinding,
    discovery: DiscoveryResult,
) -> bool:
    """Return whether one persisted profile matches source and policy identity."""

    try:
        policy = load_project_capability_profiler_policy(repo_root)
        profile = parse_project_capability_profile(
            payload,
            discovery=discovery,
            policy=policy,
        )
    except (ProjectCapabilityProfileError, OSError, ValueError):
        return False
    profiler = profile["profiler"]
    return bool(
        profile["project_id"] == project_id
        and profile["binding_id"] == binding.binding_id
        and profile["binding_revision"] == binding.revision
        and profiler["profiler_id"] == policy.profiler_id
        and profiler["profiler_revision"] == policy.profiler_revision
        and profiler["policy_digest"] == policy.policy_digest
    )


def project_capability_public_summary(profile: Mapping[str, object]) -> dict[str, object]:
    """Return a compact profile summary with no evidence paths."""

    parsed = parse_project_capability_profile(dict(profile))
    dimensions = parsed["dimensions"]
    return {
        "profile_version": parsed["schema_version"],
        "profile_digest": parsed["profile_digest"],
        "policy_digest": parsed["profiler"]["policy_digest"],
        "categories": {
            category: sorted({item["capability_id"] for item in dimensions[category]})
            for category in CATEGORIES
        },
        "finding_count": sum(len(dimensions[category]) for category in CATEGORIES),
        "evidence_count": len(parsed["evidence_catalog"]),
        "workload_ids": [item["workload_id"] for item in parsed["workload_profiles"]],
        "limitations": dict(parsed["limitations"]),
        "coverage_state": parsed["coverage_state"],
        "authoritative_for_model_assignment": parsed[
            "authoritative_for_model_assignment"
        ],
        "source_content_included": False,
        "paths_disclosed": False,
        "grants_authority": False,
    }

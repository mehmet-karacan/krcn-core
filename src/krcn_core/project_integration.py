"""Complete, freshness-aware project integration over existing KRCN services."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping

from .adapter_gate import authorize_adapter_operation, prepare_adapter_operation
from .capability_registry import load_capability_registry
from .discovery import (
    LOCAL_DISCOVERY_ADAPTER,
    DiscoveryResult,
    discover_local_source,
    load_discovery_policy,
)
from .embedding_models import load_embedding_model_catalog
from .foundation import load_json
from .hybrid_retrieval import (
    HybridIndexPlan,
    apply_hybrid_index,
    hybrid_index_is_current,
    prepare_hybrid_index,
)
from .information_records import (
    EvidenceRef,
    InformationRecord,
    Provenance,
    canonical_json,
    parse_information_record,
    payload_digest,
)
from .knowledge_catalog import InformationCatalog, build_information_catalog
from .local_store import LocalWorkspaceStore, RecordWritePlan, StoredRecord
from .mutation_gate import MutationAuthorization, OwnershipResolver
from .policies import load_user_policies
from .project_integration_state import (
    STAGE_IDS,
    ProjectIntegrationState,
    parse_project_integration_state,
)
from .project_learning import prepare_project_learning
from .project_learning_intent import parse_project_learning_intent
from .project_metadata import portable_slug
from .source_bindings import SourceBinding, parse_source_binding
from .source_code_index import (
    LOCAL_SOURCE_CODE_ADAPTER,
    SourceCodeIndexPlan,
    apply_source_code_index,
    prepare_source_code_index,
    source_code_index_is_current,
)
from .source_state import SourceState, parse_source_state


SCAN_MODES = {"manual", "automatic"}
ROLE_REFS = ("planner-agent", "read-only-worker-agent", "verifier-agent")
BASE_SKILL_REFS = (
    "project-discovery-skill",
    "project-knowledge-extraction-skill",
    "hybrid-retrieval-skill",
    "source-code-rag-skill",
)
TECHNOLOGY_SKILLS = {
    ".NET": "dotnet-project-skill",
    "Go": "go-project-skill",
    "Java": "java-project-skill",
    "Node.js": "nodejs-project-skill",
    "Python": "python-project-skill",
    "Rust": "rust-project-skill",
}
KNOWLEDGE_SUFFIXES = ("overview", "structure", "workflows", "capabilities")
SOURCE_CODE_STAGE_ID = "source-code-index"


class ProjectIntegrationError(ValueError):
    """Raised when a complete project integration cannot be planned or applied."""


@dataclass(frozen=True)
class ProjectIntegrationPolicy:
    automatic_scan_enabled: bool
    freshness_hours: int
    offline_embedding_profile_id: str


@dataclass(frozen=True)
class ProjectIntegrationPlan:
    plan_id: str
    project_id: str
    project_name: str
    source_root: Path
    binding: SourceBinding
    already_registered: bool
    scan_mode: str
    scan_reason: str
    scan_performed: bool
    scan_required: bool
    freshness_hours: int
    last_successful_scan_at: str | None
    next_automatic_scan_at: str | None
    discovery: DiscoveryResult
    missing_stages: tuple[str, ...]
    role_refs: tuple[str, ...]
    skill_refs: tuple[str, ...]
    knowledge_digest: str
    record_plans: tuple[RecordWritePlan, ...]
    future_catalog: InformationCatalog
    index_plan: HybridIndexPlan | None
    index_was_current: bool
    source_code_index_plan: SourceCodeIndexPlan | None
    source_code_index_was_current: bool
    offline_embedding_profile_id: str
    remote_embedding_profile_order: tuple[str, ...]

    @property
    def no_op(self) -> bool:
        return (
            not self.record_plans
            and self.index_plan is None
            and self.source_code_index_plan is None
        )

    def public_summary(self) -> dict[str, object]:
        stages = {
            stage: (
                "planned" if stage in self.missing_stages else "current"
            )
            for stage in (*STAGE_IDS, SOURCE_CODE_STAGE_ID)
        }
        return {
            "schema_ref": "schemas/project-integration-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "already_registered": self.already_registered,
            "scan": {
                "mode": self.scan_mode,
                "trigger": self.scan_reason,
                "performed_during_plan": self.scan_performed,
                "required": self.scan_required,
                "freshness_hours": self.freshness_hours,
                "last_successful_scan_at": self.last_successful_scan_at,
                "next_automatic_scan_at": self.next_automatic_scan_at,
                "automatic_scan_enabled": True,
                "current_root_digest": self.discovery.root_digest,
                "file_count": len(self.discovery.files),
                "technologies": list(self.discovery.technologies),
                "skipped": dict(self.discovery.skipped),
            },
            "missing_stages": list(self.missing_stages),
            "stages": stages,
            "capability_profile": {
                "role_refs": list(self.role_refs),
                "skill_refs": list(self.skill_refs),
                "selected_from_registry": True,
                "grants_authority": False,
            },
            "knowledge": {
                "planned_record_count": sum(
                    item.record_type in {"authoritative-sources", "knowledge"}
                    for item in self.record_plans
                ),
                "catalog_entry_count": len(self.future_catalog.entries),
                "knowledge_digest": self.knowledge_digest,
                "evidence_bound": True,
            },
            "vector_index": {
                "status": "current" if self.index_plan is None and self.index_was_current else "planned",
                "profile_id": self.offline_embedding_profile_id,
                "mode": "sqlite-fts-deterministic-vector",
                "remote_profile_order": list(self.remote_embedding_profile_order),
                "remote_provider_requires_session_approval": True,
                "plan": self.index_plan.public_summary() if self.index_plan else None,
            },
            "source_code_index": {
                "status": (
                    "current"
                    if self.source_code_index_plan is None
                    and self.source_code_index_was_current
                    else "planned"
                ),
                "profile_id": self.offline_embedding_profile_id,
                "mode": "contentless-sqlite-fts-deterministic-vector",
                "source_content_persisted": False,
                "source_copy": False,
                "remote_profile_order": list(self.remote_embedding_profile_order),
                "remote_provider_requires_session_approval": True,
                "plan": (
                    self.source_code_index_plan.public_summary()
                    if self.source_code_index_plan
                    else None
                ),
            },
            "record_plans": [item.public_summary() for item in self.record_plans],
            "source_access": "read-only",
            "source_copy": False,
            "remote_provider_used": False,
            "no_op": self.no_op,
        }


@dataclass(frozen=True)
class ProjectIntegrationResult:
    plan_id: str
    records: tuple[StoredRecord, ...]
    index_result: Mapping[str, object] | None
    source_code_index_result: Mapping[str, object] | None
    last_successful_scan_at: str | None

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "records": [item.public_summary() for item in self.records],
            "index": dict(self.index_result) if self.index_result else None,
            "source_code_index": (
                dict(self.source_code_index_result)
                if self.source_code_index_result
                else None
            ),
            "last_successful_scan_at": self.last_successful_scan_at,
            "source_copy": False,
            "remote_provider_used": False,
            "verified": True,
        }


def load_project_integration_policy(repo_root: Path) -> ProjectIntegrationPolicy:
    payload = load_json(repo_root / "config" / "project-integration.json")
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "schema_ref",
            "schema_version",
            "automatic_scan_enabled",
            "freshness_hours",
            "offline_embedding_profile_id",
        }
        or payload.get("schema_ref")
        != "schemas/project-integration-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("automatic_scan_enabled") is not True
        or payload.get("offline_embedding_profile_id") != "deterministic-hashing"
    ):
        raise ProjectIntegrationError("project integration policy is invalid")
    freshness = payload.get("freshness_hours")
    if (
        not isinstance(freshness, int)
        or isinstance(freshness, bool)
        or not 1 <= freshness <= 8760
    ):
        raise ProjectIntegrationError("project integration freshness is invalid")
    return ProjectIntegrationPolicy(True, freshness, "deterministic-hashing")


def _same_directory(value: object, source_root: Path) -> bool:
    if not isinstance(value, str):
        return False
    try:
        candidate = Path(value)
        return bool(
            candidate.is_absolute()
            and os.path.normcase(str(candidate.resolve()))
            == os.path.normcase(str(source_root.resolve()))
        )
    except OSError:
        return False


def _registered_project_for_source(
    store: LocalWorkspaceStore,
    source_root: Path,
) -> tuple[StoredRecord, SourceBinding] | None:
    for stored in store.list_records("source-bindings"):
        binding = parse_source_binding(stored.payload)
        if binding.locator.kind != "local-path" or not _same_directory(
            binding.locator.value,
            source_root,
        ):
            continue
        project = store.read("projects", binding.source_id)
        if project is None:
            raise ProjectIntegrationError("registered source has no project record")
        return project, binding
    return None


def _discover(
    repo_root: Path,
    store: LocalWorkspaceStore,
    binding: SourceBinding,
) -> DiscoveryResult:
    request = prepare_adapter_operation(
        LOCAL_DISCOVERY_ADAPTER,
        binding,
        "discover",
        load_user_policies(store.data_root / "policies"),
    )
    authorization = authorize_adapter_operation(request, None)
    return discover_local_source(
        binding,
        load_discovery_policy(repo_root),
        authorization,
    )


def _iso_from_mtime(mtime_ns: int | None) -> str | None:
    if mtime_ns is None:
        return None
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, timezone.utc).isoformat()


def _freshness(
    store: LocalWorkspaceStore,
    project_id: str,
    freshness_hours: int,
    now: datetime,
) -> tuple[bool, str | None, str | None]:
    modified = store.record_mtime_ns("project-integrations", project_id)
    last = _iso_from_mtime(modified)
    if modified is None:
        return False, None, None
    last_value = datetime.fromtimestamp(modified / 1_000_000_000, timezone.utc)
    next_value = last_value + timedelta(hours=freshness_hours)
    return now < next_value, last, next_value.isoformat()


def _stored_discovery(binding: SourceBinding, state: SourceState) -> DiscoveryResult:
    return DiscoveryResult(
        binding_id=binding.binding_id,
        source_id=binding.source_id,
        binding_revision=binding.revision,
        root_digest=state.root_digest,
        files=state.files,
        technologies=state.technologies,
        skipped={
            "blocked": 0,
            "symlink": 0,
            "too_large": 0,
            "unstable": 0,
            "unreadable": 0,
        },
    )


def _capability_profile(
    repo_root: Path,
    technologies: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    skills = tuple(
        dict.fromkeys(
            (*BASE_SKILL_REFS, *(TECHNOLOGY_SKILLS[item] for item in technologies if item in TECHNOLOGY_SKILLS))
        )
    )
    registry = load_capability_registry(repo_root)
    for record_id in (*ROLE_REFS, *skills):
        record = registry.get(record_id)
        if record is None or record.status != "active":
            raise ProjectIntegrationError(
                f"required integration capability is unavailable: {record_id}"
            )
    return ROLE_REFS, skills


def _modules(
    project_id: str,
    binding_id: str,
    discovery: DiscoveryResult,
) -> tuple[dict[str, object], ...]:
    counts: Counter[str] = Counter()
    for file in discovery.files:
        parts = PurePosixPath(file.relative_path).parts
        if len(parts) > 1 and not parts[0].startswith("."):
            counts[parts[0]] += 1
    selected = counts.most_common(100)
    if not selected:
        return (
            {
                "module_id": f"{project_id}-root",
                "name": "root",
                "source_ref": binding_id,
                "relative_path": ".",
            },
        )
    modules = []
    used: set[str] = set()
    for relative_path, _ in selected:
        base = portable_slug(f"{project_id}-{relative_path}")
        module_id = base
        suffix = 2
        while module_id in used:
            module_id = f"{base[:48]}-{suffix}"
            suffix += 1
        used.add(module_id)
        modules.append(
            {
                "module_id": module_id,
                "name": relative_path,
                "source_ref": binding_id,
                "relative_path": relative_path,
            }
        )
    return tuple(modules)


def _project_payload(
    current: StoredRecord | None,
    *,
    project_id: str,
    project_name: str,
    binding_id: str,
    discovery: DiscoveryResult,
    modules: tuple[dict[str, object], ...],
    skill_refs: tuple[str, ...],
) -> dict[str, object]:
    if current is None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "project_id": project_id,
            "name": project_name,
            "description": "Yerel kaynak dizini salt okunur incelenerek entegre edildi.",
            "source_refs": [binding_id],
            "technologies": [],
            "modules": [],
            "skill_refs": [],
            "status": "active",
        }
    else:
        payload = dict(current.payload)
    manual_technologies = [
        item
        for item in payload.get("technologies", [])
        if isinstance(item, dict) and item.get("category") != "discovered"
    ]
    payload["technologies"] = [
        *manual_technologies,
        *(
            {"name": technology, "category": "discovered"}
            for technology in discovery.technologies
        ),
    ]
    payload["modules"] = [dict(item) for item in modules]
    previous_skills = payload.get("skill_refs", [])
    preserved = [item for item in previous_skills if isinstance(item, str)]
    payload["skill_refs"] = list(dict.fromkeys((*preserved, *skill_refs)))
    return payload


def _workflow_names(discovery: DiscoveryResult) -> tuple[str, ...]:
    paths = {item.relative_path.casefold() for item in discovery.files}
    workflows = set()
    if any(path.endswith("pom.xml") for path in paths):
        workflows.add("Maven build")
    if any(path.endswith("package.json") for path in paths):
        workflows.add("Node.js package scripts")
    if any("/.github/workflows/" in f"/{path}" for path in paths):
        workflows.add("GitHub Actions")
    if any("test" in PurePosixPath(path).parts or "tests" in PurePosixPath(path).parts for path in paths):
        workflows.add("Automated tests")
    if any(PurePosixPath(path).name in {"dockerfile", "compose.yml", "docker-compose.yml"} for path in paths):
        workflows.add("Container workflow")
    return tuple(sorted(workflows))


def _knowledge_contents(
    project_id: str,
    project_name: str,
    discovery: DiscoveryResult,
    modules: tuple[dict[str, object], ...],
    role_refs: tuple[str, ...],
    skill_refs: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    kinds = Counter(item.kind for item in discovery.files)
    extensions = Counter(
        PurePosixPath(item.relative_path).suffix.casefold() or "[no-extension]"
        for item in discovery.files
    )
    common_extensions = ", ".join(
        f"{name} ({count})" for name, count in extensions.most_common(20)
    ) or "none"
    technologies = ", ".join(discovery.technologies) or "not identified"
    module_names = ", ".join(str(item["name"]) for item in modules) or "root"
    workflows = _workflow_names(discovery)
    workflow_text = ", ".join(workflows) or "No standard workflow marker was identified"
    return {
        "overview": {
            "title": f"{project_name} project overview",
            "text": (
                f"The read-only discovery contains {len(discovery.files)} files. "
                f"Technologies: {technologies}. Source files: {kinds['source']}; "
                f"documents: {kinds['document']}; configuration files: {kinds['configuration']}."
            ),
            "keywords": [project_id, "project", "overview", *discovery.technologies],
            "aliases": [project_name, f"{project_name} overview"],
        },
        "structure": {
            "title": f"{project_name} module and file structure",
            "text": f"Discovered modules: {module_names}. Common file extensions: {common_extensions}.",
            "keywords": [project_id, "modules", "structure"],
            "aliases": [f"{project_name} modules", f"{project_name} structure"],
        },
        "workflows": {
            "title": f"{project_name} build and verification workflows",
            "text": f"Detected workflow markers: {workflow_text}.",
            "keywords": [project_id, "build", "test", "workflow", *workflows],
            "aliases": [f"{project_name} build", f"{project_name} tests"],
        },
        "capabilities": {
            "title": f"{project_name} capability profile",
            "text": (
                "Selected roles: " + ", ".join(role_refs) + ". Selected skills: "
                + ", ".join(skill_refs) + ". Selection grants no additional authority."
            ),
            "keywords": [project_id, "roles", "skills", "capabilities"],
            "aliases": [f"{project_name} skills", f"{project_name} roles"],
        },
    }


def _source_record(
    store: LocalWorkspaceStore,
    project_id: str,
    project_name: str,
    binding: SourceBinding,
    discovery: DiscoveryResult,
) -> InformationRecord:
    record_id = f"{project_id}-source"
    current = store.read("authoritative-sources", record_id)
    revision = (current.revision if current else 0) + 1
    revision_id = f"scan-{discovery.root_digest[:16]}"
    content = {
        "title": f"{project_name} project source",
        "source_id": project_id,
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "source_revision_id": revision_id,
        "source_digest": discovery.root_digest,
        "aliases": [project_name],
    }
    return parse_information_record(
        InformationRecord(
            record_id=record_id,
            information_class="authoritative-source",
            ownership="user-data",
            subject_ref=f"source:{project_id}",
            revision=revision,
            content_digest=payload_digest(content),
            provenance=Provenance(
                "system-observation",
                (
                    EvidenceRef(
                        f"source:{project_id}",
                        revision_id,
                        discovery.root_digest,
                        "observed-at",
                    ),
                ),
            ),
            lifecycle="current",
            payload=content,
        ).as_payload()
    )


def _knowledge_records(
    store: LocalWorkspaceStore,
    project_id: str,
    source_record: InformationRecord,
    contents: Mapping[str, Mapping[str, object]],
) -> tuple[InformationRecord, ...]:
    evidence = source_record.provenance.evidence[0]
    records = []
    for suffix in KNOWLEDGE_SUFFIXES:
        record_id = f"{project_id}-{suffix}"
        current = store.read("knowledge", record_id)
        content = dict(contents[suffix])
        records.append(
            parse_information_record(
                InformationRecord(
                    record_id=record_id,
                    information_class="knowledge",
                    ownership="user-data",
                    subject_ref=f"project:{project_id}/{suffix}",
                    revision=(current.revision if current else 0) + 1,
                    content_digest=payload_digest(content),
                    provenance=Provenance(
                        "source-derived",
                        (
                            EvidenceRef(
                                evidence.source_ref,
                                evidence.revision_id,
                                evidence.digest,
                                "supports",
                            ),
                        ),
                    ),
                    lifecycle="current",
                    payload=content,
                ).as_payload()
            )
        )
    return tuple(records)


def _needs_information_update(current: StoredRecord | None, desired: InformationRecord) -> bool:
    if current is None:
        return True
    existing = parse_information_record(current.payload)
    return bool(
        existing.content_digest != desired.content_digest
        or existing.lifecycle != "current"
        or existing.provenance != desired.provenance
        or existing.subject_ref != desired.subject_ref
    )


def _desired_information_plan(
    store: LocalWorkspaceStore,
    collection: str,
    desired: InformationRecord,
) -> RecordWritePlan | None:
    current = store.read(collection, desired.record_id)
    if not _needs_information_update(current, desired):
        return None
    return store.prepare_put(
        collection,
        desired.record_id,
        desired.as_payload(),
        expected_revision=current.revision if current else 0,
    )


def _future_catalog(
    store: LocalWorkspaceStore,
    binding: SourceBinding,
    desired_records: tuple[InformationRecord, ...],
) -> InformationCatalog:
    bindings = {
        record.record_id: parse_source_binding(record.payload)
        for record in store.list_records("source-bindings")
    }
    bindings[binding.binding_id] = binding
    replacements = {record.record_id: record for record in desired_records}
    records: dict[str, InformationRecord] = {}
    for collection in ("authoritative-sources", "knowledge"):
        for stored in store.list_records(collection):
            records[stored.record_id] = replacements.pop(
                stored.record_id,
                parse_information_record(stored.payload),
            )
    records.update(replacements)
    return build_information_catalog(bindings.values(), records.values())


def _knowledge_digest(records: tuple[InformationRecord, ...]) -> str:
    identity = [
        {
            "record_id": record.record_id,
            "content_digest": record.content_digest,
            "evidence": [item.as_dict() for item in record.provenance.evidence],
        }
        for record in records
    ]
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def _integration_missing_stages(
    store: LocalWorkspaceStore,
    project_id: str,
    binding_id: str,
    role_refs: tuple[str, ...] | None,
    skill_refs: tuple[str, ...] | None,
) -> list[str]:
    missing = []
    if store.read("projects", project_id) is None or store.read("source-bindings", binding_id) is None:
        missing.append("registration")
    if store.read("source-states", binding_id) is None:
        missing.append("discovery")
    required_information = (
        ("authoritative-sources", f"{project_id}-source"),
        *(("knowledge", f"{project_id}-{suffix}") for suffix in KNOWLEDGE_SUFFIXES),
    )
    if any(store.read(collection, record_id) is None for collection, record_id in required_information):
        missing.append("knowledge")
    state_record = store.read("project-integrations", project_id)
    if state_record is None:
        missing.extend(("capability-profile", "verification"))
    else:
        state = parse_project_integration_state(state_record.payload)
        if role_refs is not None and skill_refs is not None and (
            state.role_refs != role_refs or state.skill_refs != skill_refs
        ):
            missing.append("capability-profile")
    return list(dict.fromkeys(missing))


def prepare_project_integration(
    repo_root: Path,
    store: LocalWorkspaceStore,
    *,
    source_root: Path | None = None,
    project_id: str | None = None,
    scan_mode: str = "manual",
    now: datetime | None = None,
) -> ProjectIntegrationPlan:
    """Prepare every missing or stale stage as one exact, path-redacted plan."""

    if scan_mode not in SCAN_MODES:
        raise ProjectIntegrationError("scan mode must be manual or automatic")
    if (source_root is None) == (project_id is None):
        raise ProjectIntegrationError("provide exactly one project directory or project id")
    policy = load_project_integration_policy(repo_root)
    embedding_catalog = load_embedding_model_catalog(repo_root)
    if policy.offline_embedding_profile_id != embedding_catalog.offline_fallback_id:
        raise ProjectIntegrationError(
            "project integration and embedding model policies disagree"
        )
    remote_embedding_profile_order = tuple(
        profile.profile_id for profile in embedding_catalog.remote_order
    )
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    base_plans: list[RecordWritePlan] = []
    current_project: StoredRecord | None
    previous_state: SourceState | None

    if source_root is not None:
        source_root = source_root.resolve()
        registered = _registered_project_for_source(store, source_root)
        if registered is None:
            if project_id is not None:
                raise ProjectIntegrationError("project id cannot accompany a new source")
            intent = parse_project_learning_intent(
                str(source_root),
                source_root=source_root,
                intent_terms=("integrate", "entegre"),
            )
            learning = prepare_project_learning(repo_root, store, intent)
            current_project = None
            project_id = learning.metadata.project_id
            project_name = learning.metadata.project_name
            binding = learning.binding
            discovery = learning.discovery
            base_plans.extend(
                item
                for item in learning.record_plans
                if item.record_type in {"source-bindings", "workspaces"}
            )
            already_registered = False
            previous_state = None
            scan_required = True
            scan_reason = "explicit-integration-request"
            fresh = False
            last_scan = None
            next_scan = None
            missing_stages = list(STAGE_IDS)
        else:
            current_project, binding = registered
            project_id = current_project.record_id
            project_name = str(current_project.payload.get("name", project_id))
            state_record = store.read("source-states", binding.binding_id)
            previous_state = parse_source_state(state_record.payload) if state_record else None
            role_refs, skill_refs = _capability_profile(
                repo_root,
                previous_state.technologies if previous_state else (),
            )
            missing_stages = _integration_missing_stages(
                store, project_id, binding.binding_id, role_refs, skill_refs
            )
            fresh, last_scan, next_scan = _freshness(
                store, project_id, policy.freshness_hours, current_time
            )
            scan_required = bool(
                scan_mode == "manual"
                or previous_state is None
                or missing_stages
                or not fresh
            )
            if scan_mode == "manual":
                scan_reason = "explicit-integration-request"
            elif previous_state is None:
                scan_reason = "source-state-missing"
            elif missing_stages:
                scan_reason = "missing-integration-stage"
            elif fresh:
                scan_reason = "freshness-current"
            else:
                scan_reason = "freshness-expired"
            discovery = (
                _discover(repo_root, store, binding)
                if scan_required
                else _stored_discovery(binding, previous_state)
            )
            already_registered = True
    else:
        if not isinstance(project_id, str):
            raise ProjectIntegrationError("project id is required")
        current_project = store.read("projects", project_id)
        if current_project is None:
            raise ProjectIntegrationError("project is not registered")
        source_refs = current_project.payload.get("source_refs")
        if not isinstance(source_refs, list) or len(source_refs) != 1:
            raise ProjectIntegrationError("project integration requires one source binding")
        binding_record = store.read("source-bindings", str(source_refs[0]))
        if binding_record is None:
            raise ProjectIntegrationError("project source binding is missing")
        binding = parse_source_binding(binding_record.payload)
        source_root = Path(binding.locator.value).resolve()
        project_name = str(current_project.payload.get("name", project_id))
        state_record = store.read("source-states", binding.binding_id)
        previous_state = parse_source_state(state_record.payload) if state_record else None
        role_refs, skill_refs = _capability_profile(
            repo_root,
            previous_state.technologies if previous_state else (),
        )
        missing_stages = _integration_missing_stages(
            store, project_id, binding.binding_id, role_refs, skill_refs
        )
        fresh, last_scan, next_scan = _freshness(
            store, project_id, policy.freshness_hours, current_time
        )
        scan_required = bool(
            scan_mode == "manual" or previous_state is None or missing_stages or not fresh
        )
        if scan_mode == "manual":
            scan_reason = "explicit-integration-request"
        elif previous_state is None:
            scan_reason = "source-state-missing"
        elif missing_stages:
            scan_reason = "missing-integration-stage"
        elif fresh:
            scan_reason = "freshness-current"
        else:
            scan_reason = "freshness-expired"
        discovery = (
            _discover(repo_root, store, binding)
            if scan_required
            else _stored_discovery(binding, previous_state)
        )
        already_registered = True

    assert project_id is not None and source_root is not None
    role_refs, skill_refs = _capability_profile(repo_root, discovery.technologies)
    if already_registered:
        missing_stages = _integration_missing_stages(
            store, project_id, binding.binding_id, role_refs, skill_refs
        )
    modules = _modules(project_id, binding.binding_id, discovery)
    desired_project = _project_payload(
        current_project,
        project_id=project_id,
        project_name=project_name,
        binding_id=binding.binding_id,
        discovery=discovery,
        modules=modules,
        skill_refs=skill_refs,
    )
    if current_project is None or desired_project != dict(current_project.payload):
        base_plans.append(
            store.prepare_put(
                "projects",
                project_id,
                desired_project,
                expected_revision=current_project.revision if current_project else 0,
            )
        )
    state_record = store.read("source-states", binding.binding_id)
    if (
        state_record is None
        or parse_source_state(state_record.payload).root_digest != discovery.root_digest
        or parse_source_state(state_record.payload).technologies != discovery.technologies
    ):
        state_payload = {
            "schema_version": 1,
            "binding_id": binding.binding_id,
            "binding_revision": binding.revision,
            "root_digest": discovery.root_digest,
            "files": [item.as_dict() for item in discovery.files],
            "technologies": list(discovery.technologies),
        }
        base_plans.append(
            store.prepare_put(
                "source-states",
                binding.binding_id,
                state_payload,
                expected_revision=state_record.revision if state_record else 0,
            )
        )

    source_record = _source_record(
        store, project_id, project_name, binding, discovery
    )
    contents = _knowledge_contents(
        project_id,
        project_name,
        discovery,
        modules,
        role_refs,
        skill_refs,
    )
    knowledge_records = _knowledge_records(
        store, project_id, source_record, contents
    )
    desired_information = (source_record, *knowledge_records)
    effective_information: list[InformationRecord] = []
    for collection, desired in (
        ("authoritative-sources", source_record),
        *(("knowledge", record) for record in knowledge_records),
    ):
        record_plan = _desired_information_plan(store, collection, desired)
        if record_plan is not None:
            base_plans.append(record_plan)
            effective_information.append(desired)
        else:
            current_information = store.read(collection, desired.record_id)
            if current_information is None:
                raise ProjectIntegrationError("current information record is missing")
            effective_information.append(
                parse_information_record(current_information.payload)
            )

    knowledge_digest = _knowledge_digest(desired_information)
    integration_record = store.read("project-integrations", project_id)
    current_integration = (
        parse_project_integration_state(integration_record.payload)
        if integration_record
        else None
    )
    should_update_integration = bool(
        integration_record is None
        or scan_required
        or current_integration is None
        or current_integration.source_digest != discovery.root_digest
        or current_integration.knowledge_digest != knowledge_digest
        or current_integration.role_refs != role_refs
        or current_integration.skill_refs != skill_refs
    )
    if should_update_integration:
        scan_sequence = (
            (current_integration.scan_sequence if current_integration else 0)
            + (1 if scan_required else 0)
        )
        if scan_sequence < 1:
            scan_sequence = 1
        integration_state = ProjectIntegrationState(
            project_id=project_id,
            scan_sequence=scan_sequence,
            scan_mode=scan_mode if scan_required else (current_integration.scan_mode if current_integration else scan_mode),
            scan_reason=scan_reason if scan_required else (current_integration.scan_reason if current_integration else "missing-integration-stage"),
            freshness_hours=policy.freshness_hours,
            source_digest=discovery.root_digest,
            knowledge_digest=knowledge_digest,
            embedding_profile_id=policy.offline_embedding_profile_id,
            role_refs=role_refs,
            skill_refs=skill_refs,
            stages={stage: "complete" for stage in STAGE_IDS},
        )
        base_plans.append(
            store.prepare_put(
                "project-integrations",
                project_id,
                integration_state.as_payload(),
                expected_revision=integration_record.revision if integration_record else 0,
            )
        )

    future_catalog = _future_catalog(store, binding, tuple(effective_information))
    index_was_current = hybrid_index_is_current(store.data_root, future_catalog)
    index_plan = None
    if not index_was_current:
        index_plan = prepare_hybrid_index(store.data_root, future_catalog, OwnershipResolver.from_repository(repo_root))
    if not index_was_current and "vector-index" not in missing_stages:
        missing_stages.append("vector-index")
    source_code_index_was_current = source_code_index_is_current(
        repo_root,
        store.data_root,
        project_id,
        binding.binding_id,
        discovery.root_digest,
    )
    source_code_index_plan = None
    if not source_code_index_was_current:
        source_code_request = prepare_adapter_operation(
            LOCAL_SOURCE_CODE_ADAPTER,
            binding,
            "index",
            load_user_policies(store.data_root / "policies"),
        )
        source_code_authorization = authorize_adapter_operation(
            source_code_request,
            None,
        )
        source_code_index_plan = prepare_source_code_index(
            repo_root,
            store.data_root,
            project_id,
            binding,
            source_root,
            discovery,
            OwnershipResolver.from_repository(repo_root),
            source_code_authorization,
        )
        if SOURCE_CODE_STAGE_ID not in missing_stages:
            missing_stages.append(SOURCE_CODE_STAGE_ID)
    if base_plans or index_plan is not None or source_code_index_plan is not None:
        if "verification" not in missing_stages:
            missing_stages.append("verification")

    identity = {
        "project_id": project_id,
        "source_digest": discovery.root_digest,
        "scan_mode": scan_mode,
        "scan_reason": scan_reason,
        "scan_required": scan_required,
        "missing_stages": missing_stages,
        "record_plan_ids": [item.mutation.plan_id for item in base_plans],
        "index_plan_id": index_plan.plan_id if index_plan else None,
        "source_code_index_plan_id": (
            source_code_index_plan.plan_id if source_code_index_plan else None
        ),
        "knowledge_digest": knowledge_digest,
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ProjectIntegrationPlan(
        plan_id=plan_id,
        project_id=project_id,
        project_name=project_name,
        source_root=source_root,
        binding=binding,
        already_registered=already_registered,
        scan_mode=scan_mode,
        scan_reason=scan_reason,
        scan_performed=scan_required,
        scan_required=scan_required,
        freshness_hours=policy.freshness_hours,
        last_successful_scan_at=last_scan,
        next_automatic_scan_at=next_scan,
        discovery=discovery,
        missing_stages=tuple(missing_stages),
        role_refs=role_refs,
        skill_refs=skill_refs,
        knowledge_digest=knowledge_digest,
        record_plans=tuple(base_plans),
        future_catalog=future_catalog,
        index_plan=index_plan,
        index_was_current=index_was_current,
        source_code_index_plan=source_code_index_plan,
        source_code_index_was_current=source_code_index_was_current,
        offline_embedding_profile_id=policy.offline_embedding_profile_id,
        remote_embedding_profile_order=remote_embedding_profile_order,
    )


def apply_project_integration(
    repo_root: Path,
    store: LocalWorkspaceStore,
    plan: ProjectIntegrationPlan,
    record_authorizations: Mapping[str, MutationAuthorization],
    index_authorization: MutationAuthorization | None,
    source_code_index_authorization: MutationAuthorization | None,
) -> ProjectIntegrationResult:
    """Apply the exact stages and verify that the complete lifecycle is usable."""

    if not plan.source_root.is_dir() or plan.source_root.is_symlink():
        raise ProjectIntegrationError("project source is no longer a safe directory")
    if plan.scan_performed:
        current = _discover(repo_root, store, plan.binding)
        if current.root_digest != plan.discovery.root_digest:
            raise ProjectIntegrationError("project integration plan is stale")
    for record_plan in plan.record_plans:
        store.assert_plan_current(record_plan)
        authorization = record_authorizations.get(record_plan.mutation.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != record_plan.mutation.plan_id
            or not authorization.dry_run_verified
            or (
                record_plan.mutation.approval_required
                and not authorization.approval_verified
            )
        ):
            raise ProjectIntegrationError(
                "every project integration record requires matching authorization"
            )
    order = {
        "source-bindings": 0,
        "workspaces": 1,
        "projects": 2,
        "source-states": 3,
        "authoritative-sources": 4,
        "knowledge": 5,
        "project-integrations": 6,
    }
    records = tuple(
        store.apply_put(item, record_authorizations[item.mutation.plan_id])
        for item in sorted(plan.record_plans, key=lambda candidate: order[candidate.record_type])
    )
    bindings = tuple(
        parse_source_binding(record.payload)
        for record in store.list_records("source-bindings")
    )
    information = tuple(
        parse_information_record(record.payload)
        for collection in ("authoritative-sources", "knowledge")
        for record in store.list_records(collection)
    )
    catalog = build_information_catalog(bindings, information)
    if catalog.catalog_digest != plan.future_catalog.catalog_digest:
        raise ProjectIntegrationError("project information catalog changed during apply")
    index_result = None
    if plan.index_plan is not None:
        if index_authorization is None:
            raise ProjectIntegrationError("vector index authorization is missing")
        index_result = apply_hybrid_index(
            store.data_root,
            catalog,
            plan.index_plan,
            index_authorization,
        )
    if not hybrid_index_is_current(store.data_root, catalog):
        raise ProjectIntegrationError("project vector index verification failed")
    source_code_index_result = None
    if plan.source_code_index_plan is not None:
        if source_code_index_authorization is None:
            raise ProjectIntegrationError(
                "source code index authorization is missing"
            )
        source_code_index_result = apply_source_code_index(
            store.data_root,
            plan.source_code_index_plan,
            source_code_index_authorization,
        )
    if not source_code_index_is_current(
        repo_root,
        store.data_root,
        plan.project_id,
        plan.binding.binding_id,
        plan.discovery.root_digest,
    ):
        raise ProjectIntegrationError("project source code index verification failed")
    if store.read("project-integrations", plan.project_id) is None:
        raise ProjectIntegrationError("project integration state verification failed")
    return ProjectIntegrationResult(
        plan_id=plan.plan_id,
        records=records,
        index_result=index_result,
        source_code_index_result=source_code_index_result,
        last_successful_scan_at=_iso_from_mtime(
            store.record_mtime_ns("project-integrations", plan.project_id)
        ),
    )

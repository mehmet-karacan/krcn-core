"""Deterministic readable projection over authoritative Work Graph records."""

from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TYPE_CHECKING

from .foundation import detect_content_findings, load_json
from .home_layout import project_derived_path
from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, plan_mutation

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore
    from .mutation_gate import OwnershipResolver
    from .work_graph import WorkItem


POLICY_SCHEMA = "schemas/work-index-policy.schema.json"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ACTIVE_STATUSES = {"proposed", "active", "blocked"}
ALL_STATUSES = ACTIVE_STATUSES | {"completed", "cancelled", "archived"}
WORK_TYPES = {"request", "defect", "task", "subtask", "decision"}
SENSITIVE_DETECTORS = {
    "windows-absolute-path",
    "posix-user-path",
    "private-key",
    "github-token",
    "aws-access-key",
    "generic-secret-assignment",
    "credential-uri",
}
WINDOWS_PATH = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\s\"'<>|,;)]*")
POSIX_PATH = re.compile(
    r"(?<![A-Za-z0-9_:])/(?:[A-Za-z0-9._-]+)(?:/[A-Za-z0-9._-]+)*"
)
PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
GITHUB_TOKEN = re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|"
    r"client[_-]?secret|access[_-]?token)\s*[:=]\s*"
    r"(?:[\"'][^\"'\r\n]+[\"']|[^\s,;]+)"
)
CREDENTIAL_URI = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]{1,20}://)[^\s/:@]+:[^\s/@]+@"
)


class WorkIndexError(ValueError):
    """Raised when the readable work projection is unsafe or stale."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _bytes_digest(document: bytes) -> str:
    return hashlib.sha256(document).hexdigest()


@dataclass(frozen=True)
class WorkIndexPolicy:
    renderer_revision: int
    maximum_items: int
    maximum_document_bytes: int
    maximum_title_characters: int
    active_statuses: tuple[str, ...]
    status_order: tuple[str, ...]
    work_type_order: tuple[str, ...]
    policy_digest: str


@dataclass(frozen=True)
class WorkIndexDocument:
    project_id: str
    graph_digest: str
    policy_digest: str
    document: bytes
    document_digest: str
    active_item_count: int
    historical_item_count: int
    listed_item_count: int
    omitted_item_count: int


@dataclass(frozen=True)
class WorkIndexPlan:
    project_id: str
    graph_digest: str
    policy_digest: str
    document: bytes
    document_digest: str
    active_item_count: int
    historical_item_count: int
    listed_item_count: int
    omitted_item_count: int
    target_existed: bool
    target_before_digest: str | None
    mutation: MutationPlan | None
    plan_id: str

    @property
    def no_op(self) -> bool:
        return self.mutation is None

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return () if self.mutation is None else (self.mutation,)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-index-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "graph_digest": self.graph_digest,
            "policy_digest": self.policy_digest,
            "document_digest": self.document_digest,
            "active_item_count": self.active_item_count,
            "historical_item_count": self.historical_item_count,
            "listed_item_count": self.listed_item_count,
            "omitted_item_count": self.omitted_item_count,
            "no_op": self.no_op,
            "mutation": None if self.mutation is None else self.mutation.as_dict(),
            "authoritative_source": "work-item-v1",
            "source_content_included": False,
            "evidence_references_included": False,
            "absolute_paths_included": False,
            "grants_authority": False,
        }


def load_work_index_policy(repo_root: Path) -> WorkIndexPolicy:
    payload = load_json(repo_root / "config" / "work-index.json")
    expected = {
        "schema_ref",
        "schema_version",
        "renderer_revision",
        "maximum_items",
        "maximum_document_bytes",
        "maximum_title_characters",
        "active_statuses",
        "status_order",
        "work_type_order",
        "source_content_included",
        "evidence_references_included",
        "absolute_paths_included",
        "grants_authority",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkIndexError("work index policy fields are invalid")
    if (
        payload.get("schema_ref") != POLICY_SCHEMA
        or payload.get("schema_version") != 1
        or payload.get("renderer_revision") != 1
        or payload.get("source_content_included") is not False
        or payload.get("evidence_references_included") is not False
        or payload.get("absolute_paths_included") is not False
        or payload.get("grants_authority") is not False
    ):
        raise WorkIndexError("work index policy safety fields are invalid")
    maximum_items = payload.get("maximum_items")
    maximum_bytes = payload.get("maximum_document_bytes")
    maximum_title = payload.get("maximum_title_characters")
    active = payload.get("active_statuses")
    statuses = payload.get("status_order")
    types = payload.get("work_type_order")
    if (
        not isinstance(maximum_items, int)
        or isinstance(maximum_items, bool)
        or not 1 <= maximum_items <= 100000
        or not isinstance(maximum_bytes, int)
        or isinstance(maximum_bytes, bool)
        or not 4096 <= maximum_bytes <= 16777216
        or not isinstance(maximum_title, int)
        or isinstance(maximum_title, bool)
        or not 32 <= maximum_title <= 500
        or not isinstance(active, list)
        or not active
        or any(not isinstance(value, str) for value in active)
        or len(set(active)) != len(active)
        or set(active) != ACTIVE_STATUSES
        or not isinstance(statuses, list)
        or any(not isinstance(value, str) for value in statuses)
        or len(statuses) != len(ALL_STATUSES)
        or set(statuses) != ALL_STATUSES
        or not isinstance(types, list)
        or any(not isinstance(value, str) for value in types)
        or len(types) != len(WORK_TYPES)
        or set(types) != WORK_TYPES
    ):
        raise WorkIndexError("work index policy limits or ordering are invalid")
    return WorkIndexPolicy(
        1,
        maximum_items,
        maximum_bytes,
        maximum_title,
        tuple(active),
        tuple(statuses),
        tuple(types),
        _digest(payload),
    )


def work_index_path(data_root: Path, project_id: str) -> Path:
    return project_derived_path(data_root, project_id, "work/WORK-INDEX.md")


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    os_is_junction = getattr(os.path, "isjunction", None)
    return bool(callable(os_is_junction) and os_is_junction(path))


def _assert_safe_target(data_root: Path, target: Path) -> None:
    root = data_root.resolve(strict=True)
    try:
        relative = target.relative_to(data_root)
    except ValueError as exc:
        raise WorkIndexError("work index target escaped KRCN_HOME") from exc
    candidate = root
    for part in relative.parts:
        candidate /= part
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        if _is_link_like(candidate):
            raise WorkIndexError("work index target may not use link-like ancestors")
        if candidate != target and not candidate.is_dir():
            raise WorkIndexError("work index target ancestor must be a directory")
    nearest = target.parent
    while not nearest.exists() and nearest != root:
        nearest = nearest.parent
    if _is_link_like(nearest):
        raise WorkIndexError("work index target may not use link-like ancestors")
    try:
        nearest.resolve(strict=True).relative_to(root)
        target.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise WorkIndexError("work index target resolved outside KRCN_HOME") from exc


def _safe_title(value: str, maximum: int) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = PRIVATE_KEY.sub("[redacted-secret]", normalized)
    normalized = GITHUB_TOKEN.sub("[redacted-secret]", normalized)
    normalized = SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[redacted-secret]",
        normalized,
    )
    normalized = CREDENTIAL_URI.sub(
        lambda match: f"{match.group(1)}[redacted-credentials]@",
        normalized,
    )
    normalized = WINDOWS_PATH.sub("[redacted-path]", normalized)
    normalized = POSIX_PATH.sub("[redacted-path]", normalized)
    normalized = normalized.replace(chr(0x2013), "-").replace(chr(0x2014), "-")
    normalized = " ".join(normalized.split())
    if detect_content_findings(normalized, "work-title", SENSITIVE_DETECTORS):
        normalized = "[redacted-sensitive-title]"
    if len(normalized) > maximum:
        normalized = normalized[: maximum - 3].rstrip() + "..."
    return html.escape(normalized, quote=False).replace("|", "&#124;")


def _item_key(item: "WorkItem", policy: WorkIndexPolicy) -> tuple[int, int, str]:
    return (
        policy.status_order.index(item.status),
        policy.work_type_order.index(item.work_type),
        item.work_item_id,
    )


def _table(items: Sequence["WorkItem"], policy: WorkIndexPolicy) -> str:
    if not items:
        return "_No records._\n"
    rows = [
        "| Work ID | Type | Status | Revision | Title | Relations | Evidence | Criteria |",
        "|---|---|---|---:|---|---:|---:|---:|",
    ]
    rows.extend(
        "| "
        + " | ".join((
            item.work_item_id,
            item.work_type,
            item.status,
            str(item.revision),
            _safe_title(item.title, policy.maximum_title_characters),
            str(len(item.relations)),
            str(len(item.evidence)),
            str(len(item.acceptance_criteria)),
        ))
        + " |"
        for item in items
    )
    return "\n".join(rows) + "\n"


def _render(
    project_id: str,
    graph_digest: str,
    policy: WorkIndexPolicy,
    active: Sequence["WorkItem"],
    historical: Sequence["WorkItem"],
    historical_limit: int,
) -> bytes:
    listed_history = historical[:historical_limit]
    omitted = len(historical) - len(listed_history)
    counts = {status: 0 for status in policy.status_order}
    for item in (*active, *historical):
        counts[item.status] += 1
    body = [
        f"# Work Index: {project_id}",
        "",
        "This derived view is rebuilt from authoritative Work Graph JSON records.",
        "It grants no authority and contains no source content or evidence references.",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    body.extend(f"| {status} | {counts[status]} |" for status in policy.status_order)
    body.extend((
        "",
        f"- Graph digest: `{graph_digest}`",
        f"- Listed items: {len(active) + len(listed_history)}",
        f"- Omitted historical items: {omitted}",
        "",
        "## Active work",
        "",
        _table(active, policy).rstrip(),
        "",
        "## Historical work",
        "",
        _table(listed_history, policy).rstrip(),
        "",
    ))
    body_text = "\n".join(body)
    body_digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
    metadata = (
        "<!-- krcn-work-index "
        f"schema=1 renderer={policy.renderer_revision} "
        f"graph_sha256={graph_digest} policy_sha256={policy.policy_digest} "
        f"body_sha256={body_digest} -->"
    )
    return (metadata + "\n" + body_text).encode("utf-8")


def render_work_index(
    project_id: str,
    items: Sequence["WorkItem"],
    graph_digest: str,
    policy: WorkIndexPolicy,
) -> WorkIndexDocument:
    if not IDENTIFIER.fullmatch(project_id) or not SHA256.fullmatch(graph_digest):
        raise WorkIndexError("work index identity or graph digest is invalid")
    if any(item.project_id != project_id for item in items):
        raise WorkIndexError("work index items belong to another project")
    if len({item.work_item_id for item in items}) != len(items):
        raise WorkIndexError("work index items contain duplicate identities")
    ordered = tuple(sorted(items, key=lambda item: _item_key(item, policy)))
    active = tuple(item for item in ordered if item.status in policy.active_statuses)
    historical = tuple(item for item in ordered if item.status not in policy.active_statuses)
    if len(active) > policy.maximum_items:
        raise WorkIndexError("active work exceeds the readable index item limit")
    history_limit = min(len(historical), policy.maximum_items - len(active))
    document = _render(project_id, graph_digest, policy, active, historical, history_limit)
    if len(document) > policy.maximum_document_bytes and history_limit > 0:
        lower = 0
        upper = history_limit - 1
        best_limit = 0
        best_document = _render(
            project_id, graph_digest, policy, active, historical, 0
        )
        while lower <= upper:
            candidate_limit = (lower + upper) // 2
            candidate = _render(
                project_id,
                graph_digest,
                policy,
                active,
                historical,
                candidate_limit,
            )
            if len(candidate) <= policy.maximum_document_bytes:
                best_limit = candidate_limit
                best_document = candidate
                lower = candidate_limit + 1
            else:
                upper = candidate_limit - 1
        history_limit = best_limit
        document = best_document
    if len(document) > policy.maximum_document_bytes:
        raise WorkIndexError("active work exceeds the readable index byte limit")
    return WorkIndexDocument(
        project_id,
        graph_digest,
        policy.policy_digest,
        document,
        _bytes_digest(document),
        len(active),
        len(historical),
        len(active) + history_limit,
        len(historical) - history_limit,
    )


def _read_target(data_root: Path, target: Path) -> bytes | None:
    _assert_safe_target(data_root, target)
    if not target.exists():
        return None
    if _is_link_like(target) or not target.is_file():
        raise WorkIndexError("work index target must be a regular file")
    return target.read_bytes()


def assert_work_index_preflight(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    plan: WorkIndexPlan,
) -> None:
    """Validate policy and target state before any authoritative write."""

    if load_work_index_policy(repo_root).policy_digest != plan.policy_digest:
        raise WorkIndexError("work index policy changed after planning")
    target = work_index_path(store.data_root, plan.project_id)
    current = _read_target(store.data_root, target)
    existed = current is not None
    digest = None if current is None else _bytes_digest(current)
    if existed != plan.target_existed or digest != plan.target_before_digest:
        raise WorkIndexError("work index target changed after planning")


def prepare_work_index_from_items(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    project_id: str,
    items: Sequence["WorkItem"],
    graph_digest: str,
) -> WorkIndexPlan:
    policy = load_work_index_policy(repo_root)
    rendered = render_work_index(project_id, items, graph_digest, policy)
    target = work_index_path(store.data_root, project_id)
    current = _read_target(store.data_root, target)
    target_existed = current is not None
    before_digest = None if current is None else _bytes_digest(current)
    mutation = None
    if current != rendered.document:
        target_ref = ".krcn/" + target.relative_to(store.data_root).as_posix()
        mutation = plan_mutation(
            ownership,
            operation="update" if target_existed else "create",
            target_ref=target_ref,
            expected_ownership="derived",
            change_digest=rendered.document_digest,
            reversible=True,
        )
    plan_id = _digest({
        "project_id": project_id,
        "graph_digest": graph_digest,
        "policy_digest": policy.policy_digest,
        "document_digest": rendered.document_digest,
        "target_existed": target_existed,
        "target_before_digest": before_digest,
        "mutation": None if mutation is None else mutation.as_dict(),
    })
    return WorkIndexPlan(
        project_id,
        graph_digest,
        policy.policy_digest,
        rendered.document,
        rendered.document_digest,
        rendered.active_item_count,
        rendered.historical_item_count,
        rendered.listed_item_count,
        rendered.omitted_item_count,
        target_existed,
        before_digest,
        mutation,
        plan_id,
    )


def prepare_work_index(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    project_id: str,
) -> WorkIndexPlan:
    from .work_graph import parse_work_item, work_graph_digest

    items = tuple(sorted(
        (
            item
            for item in (
                parse_work_item(record.payload)
                for record in store.list_records("work-items")
            )
            if item.project_id == project_id
        ),
        key=lambda item: item.work_item_id,
    ))
    return prepare_work_index_from_items(
        repo_root,
        store,
        ownership,
        project_id,
        items,
        work_graph_digest(store, project_id),
    )


def _atomic_write(data_root: Path, target: Path, document: bytes) -> None:
    _assert_safe_target(data_root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_target(data_root, target)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=".work-index-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(document)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def apply_work_index(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    plan: WorkIndexPlan,
    authorization: MutationAuthorization | None,
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    if expected_plan_id != plan.plan_id:
        raise WorkIndexError("work index apply requires the exact plan id")
    assert_work_index_preflight(repo_root, store, plan)
    current_plan = prepare_work_index(repo_root, store, ownership, plan.project_id)
    if (
        current_plan.graph_digest != plan.graph_digest
        or current_plan.policy_digest != plan.policy_digest
        or current_plan.document_digest != plan.document_digest
        or current_plan.target_existed != plan.target_existed
        or current_plan.target_before_digest != plan.target_before_digest
        or current_plan.plan_id != plan.plan_id
    ):
        raise WorkIndexError("work index plan became stale before apply")
    if plan.mutation is None:
        if authorization is not None:
            raise WorkIndexError("current work index does not accept authorization")
        status = "current"
    else:
        if (
            authorization is None
            or authorization.plan != plan.mutation
            or not authorization.dry_run_verified
            or (plan.mutation.approval_required and not authorization.approval_verified)
        ):
            raise WorkIndexError("work index authorization is invalid")
        target = work_index_path(store.data_root, plan.project_id)
        _atomic_write(store.data_root, target, plan.document)
        stored = _read_target(store.data_root, target)
        if stored != plan.document or _bytes_digest(stored) != plan.document_digest:
            raise WorkIndexError("work index post-write verification failed")
        status = "applied"
    return {
        "schema_ref": "schemas/work-index-result.schema.json",
        "schema_version": 1,
        "project_id": plan.project_id,
        "status": status,
        "graph_digest": plan.graph_digest,
        "document_digest": plan.document_digest,
        "active_item_count": plan.active_item_count,
        "historical_item_count": plan.historical_item_count,
        "listed_item_count": plan.listed_item_count,
        "omitted_item_count": plan.omitted_item_count,
        "authoritative_status": False,
        "derived_projection": True,
        "paths_disclosed": False,
        "grants_authority": False,
    }


def work_index_summary(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    project_id: str,
) -> dict[str, object]:
    plan = prepare_work_index(repo_root, store, ownership, project_id)
    return {
        **plan.public_summary(),
        "current": plan.no_op,
    }

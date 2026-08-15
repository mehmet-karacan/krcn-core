"""Bounded continuity records for model, client, and session changes.

Work Graph items, orchestration state, events, checkpoints, and handoffs already
survive a closed chat. What they do not provide is a small, size-bounded record
that a fresh model can read first. Reading the full history costs context and
buries the decisions and failed attempts that matter most after a compaction.

This module adds three records on top of the authoritative ones:

- `ContinuitySnapshot`: a bounded projection read first by a new session.
- `WorkJournalEvent`: an append-only, digest-linked operational history entry.
- `FinalizedHandoff`: a portable summary that carries no execution authority.

None of them is authoritative. A snapshot that contradicts the authoritative
state is rejected instead of trusted, and no record here grants authority,
carries an active lease, or exposes a machine-specific path.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Sequence


SNAPSHOT_SOFT_LIMIT_BYTES = 24576
SNAPSHOT_HARD_LIMIT_BYTES = 32768
SECTION_ITEM_LIMIT = 20

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")

# Free text in these records is operational evidence, never a location on disk
# and never a credential. Both checks fail closed instead of redacting silently.
ABSOLUTE_PATH = re.compile(
    r"(^|[^A-Za-z0-9])([A-Za-z]:[\\/]|\\\\[^\\]|/(?:home|Users|root|mnt|var)/)"
)
SECRET_MARKER = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|"
    r"client[_-]?secret|bearer)\b\s*[:=]"
)

JOURNAL_EVENT_KINDS = (
    "step-started",
    "step-completed",
    "step-failed",
    "test-failed",
    "test-passed",
    "error-observed",
    "root-cause-found",
    "approach-rejected",
    "decision-recorded",
    "decision-superseded",
    "artifact-produced",
    "source-revision-changed",
    "approval-granted",
    "approval-rejected",
    "actor-changed",
    "handoff-created",
)

# Trimmed first when the snapshot exceeds its soft limit. Identity, goal,
# status, the current step, and the next safe actions are never trimmed.
TRIM_ORDER = (
    "open_risks",
    "changed_artifacts",
    "failed_attempts",
    "known_errors",
    "verification_refs",
    "decisions",
    "completed_steps",
)

SNAPSHOT_SECTIONS = (
    "completed_steps",
    "next_safe_actions",
    "decisions",
    "failed_attempts",
    "known_errors",
    "open_risks",
    "changed_artifacts",
    "verification_refs",
    "source_binding_refs",
)

SNAPSHOT_KEYS = {
    "schema_ref",
    "schema_version",
    "snapshot_id",
    "project_id",
    "work_item_id",
    "goal",
    "status",
    "current_step",
    "approval_state",
    "work_item_revision",
    "state_digest",
    "last_handoff_ref",
    "branch",
    "baseline_commit",
    "current_commit",
    "catalog_ref",
    "updated_at",
    *SNAPSHOT_SECTIONS,
    "grants_authority",
    "snapshot_digest",
}

JOURNAL_KEYS = {
    "schema_ref",
    "schema_version",
    "event_id",
    "work_item_id",
    "occurred_at",
    "actor",
    "kind",
    "summary",
    "evidence_refs",
    "previous_digest",
    "grants_authority",
    "event_digest",
}

HANDOFF_KEYS = {
    "schema_ref",
    "schema_version",
    "handoff_id",
    "project_id",
    "work_item_id",
    "goal",
    "status",
    "completed_step_ids",
    "pending_step_ids",
    "decisions",
    "open_risks",
    "first_reads",
    "next_safe_action",
    "requires_fresh_authorization",
    "snapshot_digest",
    "created_at",
    "grants_authority",
    "carries_active_lease",
    "handoff_digest",
}


class ContinuityError(ValueError):
    """Raised when a continuity record is unusable or unsafe."""


def _digest(payload: Mapping[str, object], digest_field: str) -> str:
    identity = {key: value for key, value in payload.items() if key != digest_field}
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _payload_bytes(payload: Mapping[str, object]) -> int:
    return len(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def _safe_text(value: object, label: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContinuityError(f"{label} must be a non-empty string")
    text = value.strip()
    if len(text) > limit:
        raise ContinuityError(f"{label} exceeds {limit} characters")
    if ABSOLUTE_PATH.search(text):
        raise ContinuityError(f"{label} must not contain a machine-specific path")
    if SECRET_MARKER.search(text):
        raise ContinuityError(f"{label} must not contain a credential")
    return text


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContinuityError(f"{label} must be a portable identifier")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ContinuityError(f"{label} must be an ISO 8601 timestamp")
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ContinuityError(f"{label} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContinuityError(f"{label} must carry a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _entries(values: object, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ContinuityError(f"{label} must be a list")
    entries = tuple(_safe_text(item, f"{label} entry") for item in values)
    if len(set(entries)) != len(entries):
        raise ContinuityError(f"{label} must not contain duplicate entries")
    return entries


def _require_exact_keys(
    payload: Mapping[str, object], expected: set[str], label: str
) -> None:
    keys = set(payload)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ContinuityError(f"{label} fields are invalid: {'; '.join(details)}")


@dataclass(frozen=True)
class SnapshotSection:
    """One bounded snapshot section plus what was left in canonical records."""

    entries: tuple[str, ...] = ()
    omitted_count: int = 0

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"entries": list(self.entries)}
        if self.omitted_count:
            payload["omitted_count"] = self.omitted_count
        return payload


@dataclass(frozen=True)
class ContinuitySnapshot:
    """Bounded projection a new model reads before any other continuity record."""

    snapshot_id: str
    project_id: str
    work_item_id: str
    goal: str
    status: str
    current_step: str | None
    sections: Mapping[str, SnapshotSection]
    approval_state: str
    work_item_revision: int
    state_digest: str | None
    last_handoff_ref: str | None
    branch: str | None
    baseline_commit: str | None
    current_commit: str | None
    updated_at: str
    snapshot_digest: str
    catalog_ref: str

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_ref": "schemas/continuity-snapshot.schema.json",
            "schema_version": 1,
            "snapshot_id": self.snapshot_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "goal": self.goal,
            "status": self.status,
            "current_step": self.current_step,
            "approval_state": self.approval_state,
            "work_item_revision": self.work_item_revision,
            "state_digest": self.state_digest,
            "last_handoff_ref": self.last_handoff_ref,
            "branch": self.branch,
            "baseline_commit": self.baseline_commit,
            "current_commit": self.current_commit,
            "catalog_ref": self.catalog_ref,
            "updated_at": self.updated_at,
            "grants_authority": False,
        }
        for name in SNAPSHOT_SECTIONS:
            payload[name] = self.sections[name].as_dict()
        payload["snapshot_digest"] = self.snapshot_digest
        return payload

    @property
    def byte_size(self) -> int:
        return _payload_bytes(self.as_dict())


def _section(values: object, label: str) -> SnapshotSection:
    entries = _entries(values, label)
    if len(entries) <= SECTION_ITEM_LIMIT:
        return SnapshotSection(entries=entries)
    return SnapshotSection(
        entries=entries[-SECTION_ITEM_LIMIT:],
        omitted_count=len(entries) - SECTION_ITEM_LIMIT,
    )


def _trim_to_limit(
    sections: dict[str, SnapshotSection],
    build: "callable",
) -> dict[str, SnapshotSection]:
    """Fold the oldest low-priority entries into counts until the payload fits."""

    for name in TRIM_ORDER:
        while _payload_bytes(build(sections)) > SNAPSHOT_SOFT_LIMIT_BYTES:
            section = sections[name]
            if not section.entries:
                break
            sections[name] = SnapshotSection(
                entries=section.entries[1:],
                omitted_count=section.omitted_count + 1,
            )
        if _payload_bytes(build(sections)) <= SNAPSHOT_SOFT_LIMIT_BYTES:
            break
    return sections


def build_continuity_snapshot(
    *,
    snapshot_id: str,
    project_id: str,
    work_item_id: str,
    goal: str,
    status: str,
    updated_at: str,
    work_item_revision: int,
    approval_state: str = "current",
    current_step: str | None = None,
    completed_steps: Sequence[str] = (),
    next_safe_actions: Sequence[str] = (),
    decisions: Sequence[str] = (),
    failed_attempts: Sequence[str] = (),
    known_errors: Sequence[str] = (),
    open_risks: Sequence[str] = (),
    changed_artifacts: Sequence[str] = (),
    verification_refs: Sequence[str] = (),
    source_binding_refs: Sequence[str] = (),
    state_digest: str | None = None,
    last_handoff_ref: str | None = None,
    branch: str | None = None,
    baseline_commit: str | None = None,
    current_commit: str | None = None,
    catalog_ref: str = "work-journal",
) -> ContinuitySnapshot:
    """Build a deterministic snapshot that respects the section and size bounds."""

    if approval_state not in {"current", "fresh-authorization-required"}:
        raise ContinuityError("approval state is invalid")
    if (
        isinstance(work_item_revision, bool)
        or not isinstance(work_item_revision, int)
        or work_item_revision < 1
    ):
        raise ContinuityError("work item revision must be a positive integer")
    if state_digest is not None and not DIGEST.fullmatch(state_digest):
        raise ContinuityError("state digest is invalid")
    for value, label in (
        (branch, "branch"),
        (baseline_commit, "baseline commit"),
        (current_commit, "current commit"),
    ):
        if value is None:
            continue
        pattern = BRANCH if label == "branch" else COMMIT
        if not pattern.fullmatch(value):
            raise ContinuityError(f"{label} is invalid")

    sections = {
        "completed_steps": _section(completed_steps, "completed steps"),
        "next_safe_actions": _section(next_safe_actions, "next safe actions"),
        "decisions": _section(decisions, "decisions"),
        "failed_attempts": _section(failed_attempts, "failed attempts"),
        "known_errors": _section(known_errors, "known errors"),
        "open_risks": _section(open_risks, "open risks"),
        "changed_artifacts": _section(changed_artifacts, "changed artifacts"),
        "verification_refs": _section(verification_refs, "verification refs"),
        "source_binding_refs": _section(source_binding_refs, "source binding refs"),
    }

    base = {
        "snapshot_id": _identifier(snapshot_id, "snapshot id"),
        "project_id": _identifier(project_id, "project id"),
        "work_item_id": _identifier(work_item_id, "work item id"),
        "goal": _safe_text(goal, "goal", limit=280),
        "status": _safe_text(status, "status", limit=64),
        "current_step": (
            _safe_text(current_step, "current step") if current_step else None
        ),
        "approval_state": approval_state,
        "work_item_revision": work_item_revision,
        "state_digest": state_digest,
        "last_handoff_ref": (
            _identifier(last_handoff_ref, "last handoff ref")
            if last_handoff_ref
            else None
        ),
        "branch": branch,
        "baseline_commit": baseline_commit,
        "current_commit": current_commit,
        "catalog_ref": _safe_text(catalog_ref, "catalog ref", limit=128),
        "updated_at": _timestamp(updated_at, "updated at"),
    }

    def build(current: Mapping[str, SnapshotSection]) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_ref": "schemas/continuity-snapshot.schema.json",
            "schema_version": 1,
            **base,
            "grants_authority": False,
        }
        for name in SNAPSHOT_SECTIONS:
            payload[name] = current[name].as_dict()
        payload["snapshot_digest"] = ""
        return payload

    if _payload_bytes(build(sections)) > SNAPSHOT_SOFT_LIMIT_BYTES:
        sections = _trim_to_limit(dict(sections), build)

    payload = build(sections)
    size = _payload_bytes(payload)
    if size > SNAPSHOT_HARD_LIMIT_BYTES:
        raise ContinuityError(
            f"continuity snapshot exceeds the hard limit: {size} bytes"
        )

    snapshot = ContinuitySnapshot(
        sections=sections,
        snapshot_digest=_digest(payload, "snapshot_digest"),
        **base,
    )
    return snapshot


def parse_continuity_snapshot(payload: object) -> ContinuitySnapshot:
    """Parse a persisted snapshot and reject an unsafe or oversized record."""

    if not isinstance(payload, Mapping):
        raise ContinuityError("continuity snapshot must be an object")
    _require_exact_keys(payload, SNAPSHOT_KEYS, "continuity snapshot")
    if payload.get("schema_ref") != "schemas/continuity-snapshot.schema.json":
        raise ContinuityError("continuity snapshot schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ContinuityError("continuity snapshot schema version is invalid")
    if payload.get("grants_authority") is not False:
        raise ContinuityError("continuity snapshot must not grant authority")

    sections: dict[str, Sequence[str]] = {}
    omitted: dict[str, int] = {}
    for name in SNAPSHOT_SECTIONS:
        section = payload.get(name)
        if not isinstance(section, Mapping):
            raise ContinuityError(f"{name} section is invalid")
        entries = section.get("entries")
        if not isinstance(entries, list):
            raise ContinuityError(f"{name} entries must be a list")
        if len(entries) > SECTION_ITEM_LIMIT:
            raise ContinuityError(f"{name} exceeds the section item limit")
        section_keys = set(section)
        if not section_keys.issubset({"entries", "omitted_count"}):
            raise ContinuityError(f"{name} section fields are invalid")
        count = section.get("omitted_count", 0)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or ("omitted_count" in section and count == 0)
        ):
            raise ContinuityError(f"{name} omitted count is invalid")
        sections[name] = entries
        omitted[name] = count

    snapshot = build_continuity_snapshot(
        snapshot_id=payload.get("snapshot_id"),
        project_id=payload.get("project_id"),
        work_item_id=payload.get("work_item_id"),
        goal=payload.get("goal"),
        status=payload.get("status"),
        updated_at=payload.get("updated_at"),
        work_item_revision=payload.get("work_item_revision"),
        approval_state=payload.get("approval_state"),
        current_step=payload.get("current_step"),
        state_digest=payload.get("state_digest"),
        last_handoff_ref=payload.get("last_handoff_ref"),
        branch=payload.get("branch"),
        baseline_commit=payload.get("baseline_commit"),
        current_commit=payload.get("current_commit"),
        catalog_ref=payload.get("catalog_ref", "work-journal"),
        **{name: sections[name] for name in SNAPSHOT_SECTIONS},
    )
    restored = ContinuitySnapshot(
        snapshot_id=snapshot.snapshot_id,
        project_id=snapshot.project_id,
        work_item_id=snapshot.work_item_id,
        goal=snapshot.goal,
        status=snapshot.status,
        current_step=snapshot.current_step,
        sections={
            name: SnapshotSection(
                entries=tuple(sections[name]), omitted_count=omitted[name]
            )
            for name in SNAPSHOT_SECTIONS
        },
        approval_state=snapshot.approval_state,
        work_item_revision=snapshot.work_item_revision,
        state_digest=snapshot.state_digest,
        last_handoff_ref=snapshot.last_handoff_ref,
        branch=snapshot.branch,
        baseline_commit=snapshot.baseline_commit,
        current_commit=snapshot.current_commit,
        updated_at=snapshot.updated_at,
        snapshot_digest="",
        catalog_ref=snapshot.catalog_ref,
    )
    expected = _digest(restored.as_dict(), "snapshot_digest")
    if payload.get("snapshot_digest") != expected:
        raise ContinuityError("continuity snapshot digest does not match its content")
    return ContinuitySnapshot(
        snapshot_id=restored.snapshot_id,
        project_id=restored.project_id,
        work_item_id=restored.work_item_id,
        goal=restored.goal,
        status=restored.status,
        current_step=restored.current_step,
        sections=restored.sections,
        approval_state=restored.approval_state,
        work_item_revision=restored.work_item_revision,
        state_digest=restored.state_digest,
        last_handoff_ref=restored.last_handoff_ref,
        branch=restored.branch,
        baseline_commit=restored.baseline_commit,
        current_commit=restored.current_commit,
        updated_at=restored.updated_at,
        snapshot_digest=expected,
        catalog_ref=restored.catalog_ref,
    )


def verify_continuity_snapshot(
    snapshot: ContinuitySnapshot,
    *,
    work_item_revision: int,
    completed_step_ids: Sequence[str] = (),
    state_digest: str | None = None,
    source_revision_changed: bool = False,
) -> list[str]:
    """Reject a snapshot that contradicts the authoritative records."""

    errors: list[str] = []
    if snapshot.work_item_revision != work_item_revision:
        errors.append(
            "snapshot work item revision does not match the authoritative record"
        )
    if state_digest is not None and snapshot.state_digest != state_digest:
        errors.append("snapshot state digest does not match the authoritative record")
    if source_revision_changed:
        errors.append("snapshot source revision is stale")

    authoritative = set(completed_step_ids)
    claimed = set(snapshot.sections["completed_steps"].entries)
    if not snapshot.sections["completed_steps"].omitted_count:
        unknown = sorted(claimed - authoritative)
        if unknown:
            errors.append(
                "snapshot claims steps the authoritative state does not record: "
                + ", ".join(unknown)
            )
    return errors


@dataclass(frozen=True)
class WorkJournalEvent:
    """One append-only operational history entry with a digest link."""

    event_id: str
    work_item_id: str
    occurred_at: str
    actor: str
    kind: str
    summary: str
    evidence_refs: tuple[str, ...]
    previous_digest: str | None
    event_digest: str

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_ref": "schemas/work-journal-event.schema.json",
            "schema_version": 1,
            "event_id": self.event_id,
            "work_item_id": self.work_item_id,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "kind": self.kind,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "previous_digest": self.previous_digest,
            "grants_authority": False,
            "event_digest": self.event_digest,
        }
        return payload


def build_journal_event(
    *,
    event_id: str,
    work_item_id: str,
    occurred_at: str,
    actor: str,
    kind: str,
    summary: str,
    evidence_refs: Sequence[str] = (),
    previous: WorkJournalEvent | None = None,
) -> WorkJournalEvent:
    """Append one meaningful event to the digest-linked journal chain."""

    if kind not in JOURNAL_EVENT_KINDS:
        raise ContinuityError(f"journal event kind is unsupported: {kind}")
    payload = {
        "schema_ref": "schemas/work-journal-event.schema.json",
        "schema_version": 1,
        "event_id": _identifier(event_id, "event id"),
        "work_item_id": _identifier(work_item_id, "work item id"),
        "occurred_at": _timestamp(occurred_at, "occurred at"),
        "actor": _safe_text(actor, "actor", limit=128),
        "kind": kind,
        "summary": _safe_text(summary, "summary", limit=512),
        "evidence_refs": list(_entries(evidence_refs, "evidence refs")),
        "previous_digest": previous.event_digest if previous else None,
        "grants_authority": False,
    }
    return WorkJournalEvent(
        event_id=payload["event_id"],
        work_item_id=payload["work_item_id"],
        occurred_at=payload["occurred_at"],
        actor=payload["actor"],
        kind=kind,
        summary=payload["summary"],
        evidence_refs=tuple(payload["evidence_refs"]),
        previous_digest=payload["previous_digest"],
        event_digest=_digest(payload, "event_digest"),
    )


def parse_work_journal_event(payload: object) -> WorkJournalEvent:
    """Parse one persisted journal event without weakening its digest chain."""

    if not isinstance(payload, Mapping):
        raise ContinuityError("work journal event must be an object")
    _require_exact_keys(payload, JOURNAL_KEYS, "work journal event")
    if payload.get("schema_ref") != "schemas/work-journal-event.schema.json":
        raise ContinuityError("work journal event schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ContinuityError("work journal event schema version is invalid")
    if payload.get("grants_authority") is not False:
        raise ContinuityError("work journal event must not grant authority")
    kind = payload.get("kind")
    if kind not in JOURNAL_EVENT_KINDS:
        raise ContinuityError("work journal event kind is unsupported")
    previous_digest = payload.get("previous_digest")
    if previous_digest is not None and (
        not isinstance(previous_digest, str) or not DIGEST.fullmatch(previous_digest)
    ):
        raise ContinuityError("work journal previous digest is invalid")

    event = WorkJournalEvent(
        event_id=_identifier(payload.get("event_id"), "event id"),
        work_item_id=_identifier(payload.get("work_item_id"), "work item id"),
        occurred_at=_timestamp(payload.get("occurred_at"), "occurred at"),
        actor=_safe_text(payload.get("actor"), "actor", limit=128),
        kind=str(kind),
        summary=_safe_text(payload.get("summary"), "summary", limit=512),
        evidence_refs=_entries(payload.get("evidence_refs"), "evidence refs"),
        previous_digest=previous_digest,
        event_digest=str(payload.get("event_digest", "")),
    )
    if not DIGEST.fullmatch(event.event_digest):
        raise ContinuityError("work journal event digest is invalid")
    if _digest(event.as_dict(), "event_digest") != event.event_digest:
        raise ContinuityError("work journal event digest does not match its content")
    return event


def verify_journal_chain(events: Sequence[WorkJournalEvent]) -> list[str]:
    """Check that the journal is an unbroken, tamper-evident append-only chain."""

    errors: list[str] = []
    previous: WorkJournalEvent | None = None
    seen: set[str] = set()
    work_item_id: str | None = None
    occurred_at: str | None = None
    for position, event in enumerate(events):
        if event.event_id in seen:
            errors.append(f"journal event {event.event_id} is duplicated")
        seen.add(event.event_id)
        if work_item_id is None:
            work_item_id = event.work_item_id
        elif event.work_item_id != work_item_id:
            errors.append(f"journal event {event.event_id} belongs to another work item")
        if occurred_at is not None and event.occurred_at < occurred_at:
            errors.append(f"journal event {event.event_id} is out of time order")
        occurred_at = event.occurred_at
        expected_previous = previous.event_digest if previous else None
        if event.previous_digest != expected_previous:
            errors.append(
                f"journal event {event.event_id} does not link to position {position - 1}"
            )
        payload = event.as_dict()
        if _digest(payload, "event_digest") != event.event_digest:
            errors.append(f"journal event {event.event_id} digest does not match")
        previous = event
    return errors


@dataclass(frozen=True)
class FinalizedHandoff:
    """Portable handoff summary that never carries execution authority."""

    handoff_id: str
    project_id: str
    work_item_id: str
    goal: str
    status: str
    completed_step_ids: tuple[str, ...]
    pending_step_ids: tuple[str, ...]
    decisions: tuple[str, ...]
    open_risks: tuple[str, ...]
    first_reads: tuple[str, ...]
    next_safe_action: str | None
    requires_fresh_authorization: bool
    snapshot_digest: str
    created_at: str
    handoff_digest: str = field(default="")

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_ref": "schemas/finalized-handoff.schema.json",
            "schema_version": 1,
            "handoff_id": self.handoff_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "goal": self.goal,
            "status": self.status,
            "completed_step_ids": list(self.completed_step_ids),
            "pending_step_ids": list(self.pending_step_ids),
            "decisions": list(self.decisions),
            "open_risks": list(self.open_risks),
            "first_reads": list(self.first_reads),
            "next_safe_action": self.next_safe_action,
            "requires_fresh_authorization": self.requires_fresh_authorization,
            "snapshot_digest": self.snapshot_digest,
            "created_at": self.created_at,
            "grants_authority": False,
            "carries_active_lease": False,
            "handoff_digest": self.handoff_digest,
        }
        return payload


def finalize_handoff(
    snapshot: ContinuitySnapshot,
    *,
    handoff_id: str,
    created_at: str,
    pending_step_ids: Sequence[str] = (),
    first_reads: Sequence[str] = (),
) -> FinalizedHandoff:
    """Project a portable handoff from a snapshot without any authority field.

    The runtime handoff keeps an authorization identifier and a resume token so
    that the same session can continue. A finalized handoff is read by another
    model, client, or device, so both are dropped and a fresh authorization is
    required whenever the snapshot is not in a clean approval state.
    """

    handoff = FinalizedHandoff(
        handoff_id=_identifier(handoff_id, "handoff id"),
        project_id=snapshot.project_id,
        work_item_id=snapshot.work_item_id,
        goal=snapshot.goal,
        status=snapshot.status,
        completed_step_ids=snapshot.sections["completed_steps"].entries,
        pending_step_ids=_entries(pending_step_ids, "pending step ids"),
        decisions=snapshot.sections["decisions"].entries,
        open_risks=snapshot.sections["open_risks"].entries,
        first_reads=_entries(first_reads, "first reads"),
        next_safe_action=(
            snapshot.sections["next_safe_actions"].entries[0]
            if snapshot.sections["next_safe_actions"].entries
            else None
        ),
        requires_fresh_authorization=snapshot.approval_state
        != "current",
        snapshot_digest=snapshot.snapshot_digest,
        created_at=_timestamp(created_at, "created at"),
    )
    return FinalizedHandoff(
        handoff_id=handoff.handoff_id,
        project_id=handoff.project_id,
        work_item_id=handoff.work_item_id,
        goal=handoff.goal,
        status=handoff.status,
        completed_step_ids=handoff.completed_step_ids,
        pending_step_ids=handoff.pending_step_ids,
        decisions=handoff.decisions,
        open_risks=handoff.open_risks,
        first_reads=handoff.first_reads,
        next_safe_action=handoff.next_safe_action,
        requires_fresh_authorization=handoff.requires_fresh_authorization,
        snapshot_digest=handoff.snapshot_digest,
        created_at=handoff.created_at,
        handoff_digest=_digest(handoff.as_dict(), "handoff_digest"),
    )


def parse_finalized_handoff(payload: object) -> FinalizedHandoff:
    """Parse a portable handoff and reject any authority or lease claim."""

    if not isinstance(payload, Mapping):
        raise ContinuityError("finalized handoff must be an object")
    _require_exact_keys(payload, HANDOFF_KEYS, "finalized handoff")
    if payload.get("schema_ref") != "schemas/finalized-handoff.schema.json":
        raise ContinuityError("finalized handoff schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ContinuityError("finalized handoff schema version is invalid")
    if payload.get("grants_authority") is not False:
        raise ContinuityError("finalized handoff must not grant authority")
    if payload.get("carries_active_lease") is not False:
        raise ContinuityError("finalized handoff must not carry an active lease")
    for forbidden in ("authorization_id", "resume_token", "owner_token", "source_root"):
        if forbidden in payload:
            raise ContinuityError(
                f"finalized handoff must not carry {forbidden.replace('_', ' ')}"
            )

    requires_fresh_authorization = payload.get("requires_fresh_authorization")
    if not isinstance(requires_fresh_authorization, bool):
        raise ContinuityError(
            "finalized handoff fresh authorization flag must be a boolean"
        )
    snapshot_digest = payload.get("snapshot_digest")
    if not isinstance(snapshot_digest, str) or not DIGEST.fullmatch(snapshot_digest):
        raise ContinuityError("finalized handoff snapshot digest is invalid")

    handoff = FinalizedHandoff(
        handoff_id=_identifier(payload.get("handoff_id"), "handoff id"),
        project_id=_identifier(payload.get("project_id"), "project id"),
        work_item_id=_identifier(payload.get("work_item_id"), "work item id"),
        goal=_safe_text(payload.get("goal"), "goal", limit=280),
        status=_safe_text(payload.get("status"), "status", limit=64),
        completed_step_ids=_entries(payload.get("completed_step_ids"), "completed step ids"),
        pending_step_ids=_entries(payload.get("pending_step_ids"), "pending step ids"),
        decisions=_entries(payload.get("decisions"), "decisions"),
        open_risks=_entries(payload.get("open_risks"), "open risks"),
        first_reads=_entries(payload.get("first_reads"), "first reads"),
        next_safe_action=(
            _safe_text(payload.get("next_safe_action"), "next safe action")
            if payload.get("next_safe_action")
            else None
        ),
        requires_fresh_authorization=requires_fresh_authorization,
        snapshot_digest=snapshot_digest,
        created_at=_timestamp(payload.get("created_at"), "created at"),
    )
    expected = _digest(handoff.as_dict(), "handoff_digest")
    if payload.get("handoff_digest") != expected:
        raise ContinuityError("finalized handoff digest does not match its content")
    return FinalizedHandoff(
        handoff_id=handoff.handoff_id,
        project_id=handoff.project_id,
        work_item_id=handoff.work_item_id,
        goal=handoff.goal,
        status=handoff.status,
        completed_step_ids=handoff.completed_step_ids,
        pending_step_ids=handoff.pending_step_ids,
        decisions=handoff.decisions,
        open_risks=handoff.open_risks,
        first_reads=handoff.first_reads,
        next_safe_action=handoff.next_safe_action,
        requires_fresh_authorization=handoff.requires_fresh_authorization,
        snapshot_digest=handoff.snapshot_digest,
        created_at=handoff.created_at,
        handoff_digest=expected,
    )

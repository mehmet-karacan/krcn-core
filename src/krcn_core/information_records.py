"""Strict provenance and revision-aware information record contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")
REVISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
INFORMATION_CLASSES = {
    "authoritative-source",
    "knowledge",
    "memory",
    "state",
    "history",
    "derived",
}
OWNERSHIP_BY_CLASS = {
    "authoritative-source": {"user-data"},
    "knowledge": {"user-data"},
    "memory": {"user-data"},
    "state": {"runtime"},
    "history": {"runtime", "user-data"},
    "derived": {"derived"},
}
EVIDENCE_REQUIRED = {
    "authoritative-source",
    "knowledge",
    "memory",
    "history",
    "derived",
}
PROVENANCE_KINDS = {
    "explicit-user",
    "approved-import",
    "source-derived",
    "system-observation",
    "approved-memory",
}
EVIDENCE_RELATIONS = {
    "supports",
    "derived-from",
    "observed-at",
    "supersedes",
    "contradicts",
}
LIFECYCLE_STATES = {"current", "superseded", "stale", "archived"}
SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|token|api[-_]?key|secret|credential|private[-_]?key)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*="),
    re.compile(r"://[^/\s:@]+:[^/@\s]+@"),
    re.compile(r"^(?:secret|keyring|env)://", re.IGNORECASE),
)


class InformationRecordError(ValueError):
    """Raised when an information record violates authority or safety rules."""


@dataclass(frozen=True)
class EvidenceRef:
    source_ref: str
    revision_id: str
    digest: str
    relation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_ref": self.source_ref,
            "revision_id": self.revision_id,
            "digest": self.digest,
            "relation": self.relation,
        }


@dataclass(frozen=True)
class Provenance:
    kind: str
    evidence: tuple[EvidenceRef, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class InformationRecord:
    record_id: str
    information_class: str
    ownership: str
    subject_ref: str
    revision: int
    content_digest: str
    provenance: Provenance
    lifecycle: str
    payload: Mapping[str, object]

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": self.record_id,
            "information_class": self.information_class,
            "ownership": self.ownership,
            "subject_ref": self.subject_ref,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "provenance": self.provenance.as_dict(),
            "lifecycle": self.lifecycle,
            "payload": dict(self.payload),
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "information_class": self.information_class,
            "ownership": self.ownership,
            "subject_ref": self.subject_ref,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "provenance_kind": self.provenance.kind,
            "evidence_count": len(self.provenance.evidence),
            "lifecycle": self.lifecycle,
        }


def canonical_json(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InformationRecordError("information payload must be JSON-compatible") from exc


def payload_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _logical_ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise InformationRecordError(f"{label} must be a logical reference")
    namespace, identifier = value.split(":", 1)
    if (
        not namespace
        or not identifier
        or "\\" in identifier
        or ".." in identifier.split("/")
        or identifier.startswith("/")
        or "://" in value
    ):
        raise InformationRecordError(f"{label} must be portable")
    return value


def _scan_secret_free(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise InformationRecordError(
                    "information payload keys must be non-empty strings"
                )
            if SENSITIVE_KEY.search(key):
                raise InformationRecordError(
                    "secret-like fields are prohibited in information records"
                )
            _scan_secret_free(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _scan_secret_free(nested)
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS
    ):
        raise InformationRecordError(
            "secret-like values are prohibited in information records"
        )
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise InformationRecordError("information payload must be JSON-compatible")


def _parse_evidence(payload: object) -> tuple[EvidenceRef, ...]:
    if not isinstance(payload, list):
        raise InformationRecordError("provenance evidence must be a list")
    evidence = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "source_ref",
            "revision_id",
            "digest",
            "relation",
        }:
            raise InformationRecordError("evidence fields are invalid")
        source_ref = _logical_ref(item.get("source_ref"), "evidence source_ref")
        revision_id = item.get("revision_id")
        digest = item.get("digest")
        relation = item.get("relation")
        if not isinstance(revision_id, str) or not REVISION_ID.fullmatch(revision_id):
            raise InformationRecordError("evidence revision_id is invalid")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise InformationRecordError("evidence digest is invalid")
        if not isinstance(relation, str) or relation not in EVIDENCE_RELATIONS:
            raise InformationRecordError("evidence relation is invalid")
        identity = (source_ref, revision_id, digest, relation)
        if identity in seen:
            raise InformationRecordError("provenance evidence must be unique")
        seen.add(identity)
        evidence.append(EvidenceRef(*identity))
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.source_ref,
                item.revision_id,
                item.digest,
                item.relation,
            ),
        )
    )


def parse_information_record(payload: object) -> InformationRecord:
    """Parse a record while verifying digest, evidence, ownership, and secrecy."""

    expected_fields = {
        "schema_ref",
        "schema_version",
        "record_id",
        "information_class",
        "ownership",
        "subject_ref",
        "revision",
        "content_digest",
        "provenance",
        "lifecycle",
        "payload",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise InformationRecordError("information record fields are invalid")
    if payload.get("schema_ref") != "schemas/information-record.schema.json":
        raise InformationRecordError("information record schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise InformationRecordError("information record schema_version must be 1")
    record_id = payload.get("record_id")
    if not isinstance(record_id, str) or not IDENTIFIER.fullmatch(record_id):
        raise InformationRecordError("information record id is invalid")
    information_class = payload.get("information_class")
    if (
        not isinstance(information_class, str)
        or information_class not in INFORMATION_CLASSES
    ):
        raise InformationRecordError("information class is invalid")
    ownership = payload.get("ownership")
    if (
        not isinstance(ownership, str)
        or ownership not in OWNERSHIP_BY_CLASS[information_class]
    ):
        raise InformationRecordError(
            "information ownership does not match its class"
        )
    subject_ref = _logical_ref(payload.get("subject_ref"), "subject_ref")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise InformationRecordError("information revision must be positive")
    content = payload.get("payload")
    if not isinstance(content, dict):
        raise InformationRecordError("information payload must be an object")
    _scan_secret_free(content)
    digest = payload.get("content_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise InformationRecordError("information content digest is invalid")
    if payload_digest(content) != digest:
        raise InformationRecordError("information content digest does not match")
    provenance_payload = payload.get("provenance")
    if not isinstance(provenance_payload, dict) or set(provenance_payload) != {
        "kind",
        "evidence",
    }:
        raise InformationRecordError("information provenance fields are invalid")
    provenance_kind = provenance_payload.get("kind")
    if (
        not isinstance(provenance_kind, str)
        or provenance_kind not in PROVENANCE_KINDS
    ):
        raise InformationRecordError("information provenance kind is invalid")
    evidence = _parse_evidence(provenance_payload.get("evidence"))
    if information_class in EVIDENCE_REQUIRED and not evidence:
        raise InformationRecordError(
            "information class requires revision-bound evidence"
        )
    lifecycle = payload.get("lifecycle")
    if not isinstance(lifecycle, str) or lifecycle not in LIFECYCLE_STATES:
        raise InformationRecordError("information lifecycle is invalid")
    if information_class == "authoritative-source" and lifecycle == "stale":
        raise InformationRecordError(
            "authoritative source records are superseded instead of stale"
        )
    return InformationRecord(
        record_id=record_id,
        information_class=information_class,
        ownership=ownership,
        subject_ref=subject_ref,
        revision=revision,
        content_digest=digest,
        provenance=Provenance(provenance_kind, evidence),
        lifecycle=lifecycle,
        payload=dict(content),
    )


def record_is_stale(
    record: InformationRecord,
    current_revisions: Mapping[str, tuple[str, str]],
) -> bool:
    """Return whether supporting source revision evidence is no longer current."""

    if record.information_class not in {"knowledge", "memory", "derived"}:
        return False
    relevant = tuple(
        item
        for item in record.provenance.evidence
        if item.relation in {"supports", "derived-from", "observed-at"}
    )
    if not relevant:
        return True
    for evidence in relevant:
        current = current_revisions.get(evidence.source_ref)
        if current is None or current != (evidence.revision_id, evidence.digest):
            return True
    return False

"""Atomic and revision-aware local user-data and derived record storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .integrations import parse_integration_metadata
from .source_bindings import parse_source_binding
from .source_state import parse_source_state


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
COLLECTIONS = {
    "workspaces": ("workspace_id", "workspaces", "user-data"),
    "projects": ("project_id", "projects", "user-data"),
    "source-bindings": ("binding_id", "source-bindings", "user-data"),
    "integrations": ("integration_id", "integrations", "user-data"),
    "source-states": ("binding_id", "derived/source-states", "derived"),
}


class LocalStoreError(ValueError):
    """Raised when a local record cannot be planned, read, or written safely."""


class RevisionConflictError(LocalStoreError):
    """Raised when optimistic revision control detects a stale writer."""


@dataclass(frozen=True)
class StoredRecord:
    record_type: str
    record_id: str
    revision: int
    payload: Mapping[str, object]
    payload_sha256: str

    def public_summary(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "record_id": self.record_id,
            "revision": self.revision,
            "payload_sha256": self.payload_sha256,
        }


@dataclass(frozen=True)
class RecordWritePlan:
    record_type: str
    record_id: str
    previous_revision: int
    next_revision: int
    payload_sha256: str
    document: bytes
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "record_id": self.record_id,
            "previous_revision": self.previous_revision,
            "next_revision": self.next_revision,
            "payload_sha256": self.payload_sha256,
            "mutation": self.mutation.as_dict(),
        }


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _payload_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _validate_record_identity(
    record_type: str,
    record_id: str,
    payload: Mapping[str, object],
) -> None:
    collection = COLLECTIONS.get(record_type)
    if collection is None:
        raise LocalStoreError("record type is invalid")
    identity_field = collection[0]
    if not IDENTIFIER.fullmatch(record_id):
        raise LocalStoreError("record id must be portable")
    if payload.get("schema_version") != 1:
        raise LocalStoreError("payload schema_version must be 1")
    if payload.get(identity_field) != record_id:
        raise LocalStoreError("record id does not match payload identity")
    if record_type == "source-bindings":
        parse_source_binding(payload)
    if record_type == "integrations":
        parse_integration_metadata(payload)
    if record_type == "source-states":
        parse_source_state(payload)


class LocalWorkspaceStore:
    """Store preserved workspace records outside the versioned core tree."""

    def __init__(self, data_root: Path, ownership: OwnershipResolver) -> None:
        self._data_root = data_root.resolve()
        self._ownership = ownership

    @property
    def data_root(self) -> Path:
        return self._data_root

    def _target(self, record_type: str, record_id: str) -> Path:
        collection = COLLECTIONS.get(record_type)
        if collection is None:
            raise LocalStoreError("record type is invalid")
        if not IDENTIFIER.fullmatch(record_id):
            raise LocalStoreError("record id must be portable")
        return self._data_root.joinpath(*collection[1].split("/")) / f"{record_id}.json"

    def _target_ref(self, record_type: str, record_id: str) -> str:
        collection = COLLECTIONS[record_type]
        return f".krcn/{collection[1]}/{record_id}.json"

    def read(self, record_type: str, record_id: str) -> StoredRecord | None:
        target = self._target(record_type, record_id)
        if not target.exists():
            return None
        if target.is_symlink() or not target.is_file():
            raise LocalStoreError("record target must be a regular file")
        try:
            envelope = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LocalStoreError("stored record JSON is invalid") from exc
        if not isinstance(envelope, dict):
            raise LocalStoreError("stored record must be an object")
        expected_envelope_fields = {
            "schema_version",
            "record_type",
            "record_id",
            "revision",
            "payload",
            "payload_sha256",
        }
        if set(envelope) != expected_envelope_fields or envelope.get("schema_version") != 1:
            raise LocalStoreError("stored record envelope is invalid")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise LocalStoreError("stored record payload must be an object")
        _validate_record_identity(record_type, record_id, payload)
        if envelope.get("record_type") != record_type or envelope.get("record_id") != record_id:
            raise LocalStoreError("stored record envelope identity is invalid")
        revision = envelope.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise LocalStoreError("stored record revision is invalid")
        payload_sha256 = _payload_hash(payload)
        if envelope.get("payload_sha256") != payload_sha256:
            raise LocalStoreError("stored record payload hash is invalid")
        return StoredRecord(
            record_type=record_type,
            record_id=record_id,
            revision=revision,
            payload=payload,
            payload_sha256=payload_sha256,
        )

    def list_summaries(self, record_type: str) -> tuple[dict[str, object], ...]:
        directory = self._target(record_type, "placeholder").parent
        if not directory.exists():
            return ()
        if directory.is_symlink() or not directory.is_dir():
            raise LocalStoreError("record collection must be a regular directory")
        records = []
        for path in sorted(directory.glob("*.json")):
            record = self.read(record_type, path.stem)
            if record is not None:
                records.append(record.public_summary())
        return tuple(records)

    def prepare_put(
        self,
        record_type: str,
        record_id: str,
        payload: Mapping[str, object],
        *,
        expected_revision: int,
    ) -> RecordWritePlan:
        if not isinstance(payload, Mapping):
            raise LocalStoreError("record payload must be an object")
        payload_copy = dict(payload)
        _validate_record_identity(record_type, record_id, payload_copy)
        current = self.read(record_type, record_id)
        current_revision = current.revision if current else 0
        if expected_revision != current_revision:
            raise RevisionConflictError("record revision changed before planning")
        next_revision = current_revision + 1
        payload_sha256 = _payload_hash(payload_copy)
        envelope = {
            "schema_version": 1,
            "record_type": record_type,
            "record_id": record_id,
            "revision": next_revision,
            "payload": payload_copy,
            "payload_sha256": payload_sha256,
        }
        mutation = plan_mutation(
            self._ownership,
            operation="create" if current is None else "update",
            target_ref=self._target_ref(record_type, record_id),
            expected_ownership=COLLECTIONS[record_type][2],
            change_digest=payload_sha256,
            reversible=True,
        )
        return RecordWritePlan(
            record_type=record_type,
            record_id=record_id,
            previous_revision=current_revision,
            next_revision=next_revision,
            payload_sha256=payload_sha256,
            document=_canonical_json(envelope),
            mutation=mutation,
        )

    def apply_put(
        self,
        plan: RecordWritePlan,
        authorization: MutationAuthorization,
    ) -> StoredRecord:
        if authorization.plan.plan_id != plan.mutation.plan_id:
            raise LocalStoreError("mutation authorization does not match write plan")
        if not authorization.dry_run_verified:
            raise LocalStoreError("verified dry-run is required")
        if plan.mutation.approval_required and not authorization.approval_verified:
            raise LocalStoreError("user approval is required")
        self.assert_plan_current(plan)
        if plan.mutation.change_digest != plan.payload_sha256:
            raise LocalStoreError("mutation change digest does not match payload")
        try:
            planned_envelope = json.loads(plan.document)
        except json.JSONDecodeError as exc:
            raise LocalStoreError("planned record document is invalid") from exc
        if (
            not isinstance(planned_envelope, dict)
            or planned_envelope.get("payload_sha256") != plan.payload_sha256
            or planned_envelope.get("revision") != plan.next_revision
            or planned_envelope.get("record_id") != plan.record_id
            or planned_envelope.get("record_type") != plan.record_type
        ):
            raise LocalStoreError("planned record document does not match write plan")
        planned_payload = planned_envelope.get("payload")
        if not isinstance(planned_payload, dict) or _payload_hash(planned_payload) != plan.payload_sha256:
            raise LocalStoreError("planned payload does not match its change digest")
        target = self._target(plan.record_type, plan.record_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink() or target.is_symlink():
            raise LocalStoreError("record path may not use symbolic links")
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{plan.record_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(plan.document)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
            temporary_name = None
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
        stored = self.read(plan.record_type, plan.record_id)
        if stored is None or stored.revision != plan.next_revision:
            raise LocalStoreError("record verification failed after atomic write")
        return stored

    def assert_plan_current(self, plan: RecordWritePlan) -> None:
        """Verify optimistic concurrency without performing a write."""

        current = self.read(plan.record_type, plan.record_id)
        current_revision = current.revision if current else 0
        if current_revision != plan.previous_revision:
            raise RevisionConflictError("record revision changed after planning")

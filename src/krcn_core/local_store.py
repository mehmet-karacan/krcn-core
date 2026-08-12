"""Atomic and revision-aware local user-data and derived record storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .json_documents import canonical_json_bytes, pretty_json_bytes
from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .integrations import parse_integration_metadata
from .information_records import (
    InformationRecordError,
    parse_information_record,
    validate_memory_record,
)
from .dependency_retrieval import (
    DependencyRetrievalError,
    parse_information_relation,
)
from .source_bindings import parse_source_binding
from .source_state import parse_source_state
from .project_integration_state import parse_project_integration_state


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
COLLECTIONS = {
    "workspaces": ("workspace_id", "workspaces", "user-data"),
    "projects": ("project_id", "projects", "user-data"),
    "source-bindings": ("binding_id", "source-bindings", "user-data"),
    "integrations": ("integration_id", "integrations", "user-data"),
    "source-states": ("binding_id", "derived/source-states", "derived"),
    "project-integrations": (
        "project_id",
        "projects/integration-states",
        "user-data",
    ),
    "authoritative-sources": (
        "record_id",
        "knowledge/authoritative-sources",
        "user-data",
    ),
    "knowledge": ("record_id", "knowledge/records", "user-data"),
    "information-relations": (
        "relation_id",
        "knowledge/relations",
        "user-data",
    ),
    "memory": ("record_id", "memory", "user-data"),
    "orchestration-states": (
        "state_id",
        "runtime/orchestration-states",
        "runtime",
    ),
    "orchestration-events": (
        "event_id",
        "events/orchestration",
        "runtime",
    ),
    "orchestration-checkpoints": (
        "checkpoint_record_id",
        "checkpoints/orchestration",
        "runtime",
    ),
    "orchestration-handoffs": (
        "handoff_id",
        "runtime/orchestration-handoffs",
        "runtime",
    ),
}
INFORMATION_COLLECTIONS = {
    "authoritative-sources": "authoritative-source",
    "knowledge": "knowledge",
    "memory": "memory",
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
    return canonical_json_bytes(payload, trailing_newline=True)


def _payload_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _validate_record_identity(
    record_type: str,
    record_id: str,
    payload: Mapping[str, object],
) -> int | None:
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
    if record_type == "project-integrations":
        parse_project_integration_state(payload)
        return None
    if record_type == "information-relations":
        try:
            relation = parse_information_relation(payload)
        except DependencyRetrievalError as exc:
            raise LocalStoreError(str(exc)) from exc
        return relation.revision
    if record_type.startswith("orchestration-"):
        from .orchestration_state import (
            parse_orchestration_checkpoint,
            parse_orchestration_event,
            parse_orchestration_handoff,
            parse_orchestration_state,
        )

        try:
            if record_type == "orchestration-states":
                return parse_orchestration_state(payload).revision
            if record_type == "orchestration-events":
                return parse_orchestration_event(payload).revision
            if record_type == "orchestration-checkpoints":
                return parse_orchestration_checkpoint(payload)[0]
            return parse_orchestration_handoff(payload).revision
        except ValueError as exc:
            raise LocalStoreError(str(exc)) from exc
    expected_information_class = INFORMATION_COLLECTIONS.get(record_type)
    if expected_information_class is not None:
        try:
            information_record = parse_information_record(payload)
        except InformationRecordError as exc:
            raise LocalStoreError(str(exc)) from exc
        if information_record.information_class != expected_information_class:
            raise LocalStoreError(
                "information class does not match the local collection"
            )
        if record_type == "memory":
            try:
                validate_memory_record(information_record)
            except InformationRecordError as exc:
                raise LocalStoreError(str(exc)) from exc
        return information_record.revision
    return None


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

    @contextmanager
    def _record_lock(self, record_type: str, record_id: str):
        """Hold one cross-process advisory lock for a logical record."""

        self._target(record_type, record_id)
        directory = self._data_root / "locks" / "records"
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise LocalStoreError("record lock directory must be regular")
        lock_path = directory / f"{record_type}--{record_id}.lock"
        deadline = time.monotonic() + 10.0
        with lock_path.open("a+b") as stream:
            if lock_path.is_symlink():
                raise LocalStoreError("record lock may not be a symbolic link")
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            acquired = False
            if os.name == "nt":
                import msvcrt

                while not acquired:
                    try:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        acquired = True
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise LocalStoreError("record lock acquisition timed out") from exc
                        time.sleep(0.01)
            else:
                import fcntl

                while not acquired:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except BlockingIOError as exc:
                        if time.monotonic() >= deadline:
                            raise LocalStoreError("record lock acquisition timed out") from exc
                        time.sleep(0.01)
            try:
                yield
            finally:
                if acquired:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

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
        information_revision = _validate_record_identity(
            record_type,
            record_id,
            payload,
        )
        if envelope.get("record_type") != record_type or envelope.get("record_id") != record_id:
            raise LocalStoreError("stored record envelope identity is invalid")
        revision = envelope.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise LocalStoreError("stored record revision is invalid")
        if information_revision is not None and information_revision != revision:
            raise LocalStoreError(
                "information revision does not match stored record revision"
            )
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
        return tuple(
            record.public_summary() for record in self.list_records(record_type)
        )

    def list_records(self, record_type: str) -> tuple[StoredRecord, ...]:
        """Read a collection in portable identifier order."""

        directory = self._target(record_type, "placeholder").parent
        if not directory.exists():
            return ()
        if directory.is_symlink() or not directory.is_dir():
            raise LocalStoreError("record collection must be a regular directory")
        records: list[StoredRecord] = []
        for path in sorted(directory.glob("*.json")):
            record = self.read(record_type, path.stem)
            if record is not None:
                records.append(record)
        return tuple(records)

    def record_mtime_ns(self, record_type: str, record_id: str) -> int | None:
        """Return the verified record file modification time for freshness checks."""

        target = self._target(record_type, record_id)
        if not target.exists():
            return None
        if target.is_symlink() or not target.is_file():
            raise LocalStoreError("record target must be a regular file")
        self.read(record_type, record_id)
        return target.stat().st_mtime_ns

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
        information_revision = _validate_record_identity(
            record_type,
            record_id,
            payload_copy,
        )
        current = self.read(record_type, record_id)
        current_revision = current.revision if current else 0
        if expected_revision != current_revision:
            raise RevisionConflictError("record revision changed before planning")
        next_revision = current_revision + 1
        if information_revision is not None and information_revision != next_revision:
            raise LocalStoreError(
                "information revision must match the planned record revision"
            )
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
            document=pretty_json_bytes(envelope),
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
        with self._record_lock(plan.record_type, plan.record_id):
            return self._apply_put_locked(plan)

    def _apply_put_locked(self, plan: RecordWritePlan) -> StoredRecord:
        """Apply after the caller has serialized writers for this record."""

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

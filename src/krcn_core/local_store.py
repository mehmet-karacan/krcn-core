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
from .home_layout import (
    GLOBAL_COLLECTION_PATHS,
    PROJECT_COLLECTION_PATHS,
    HomeLayoutError,
    collection_target,
    home_layout_version,
    validate_project_capsule_payload,
)
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
from .work_graph import parse_work_event, parse_work_item


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
COLLECTIONS = {
    "project-capsules": ("project_id", "projects/capsules", "user-data"),
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
    "work-items": ("work_item_id", "work-items", "user-data"),
    "work-events": ("work_event_id", "work-events", "user-data"),
    "oracle-metadata-snapshots": (
        "snapshot_id",
        "database/oracle/snapshots",
        "user-data",
    ),
    "oracle-schema-objects": (
        "object_id",
        "database/oracle/objects",
        "user-data",
    ),
    "oracle-object-revisions": (
        "revision_id",
        "database/oracle/revisions",
        "user-data",
    ),
    "oracle-dependencies": (
        "dependency_id",
        "database/oracle/dependencies",
        "user-data",
    ),
    "oracle-collection-reports": (
        "report_id",
        "database/oracle/reports",
        "user-data",
    ),
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
    target: Path
    layout_version: int
    project_id: str | None
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "record_id": self.record_id,
            "previous_revision": self.previous_revision,
            "next_revision": self.next_revision,
            "payload_sha256": self.payload_sha256,
            "layout_version": self.layout_version,
            "project_id": self.project_id,
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
    if record_type == "project-capsules":
        try:
            validate_project_capsule_payload(payload, record_id)
        except HomeLayoutError as exc:
            raise LocalStoreError(str(exc)) from exc
        return None
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
    if record_type == "work-items":
        try:
            return parse_work_item(payload).revision
        except ValueError as exc:
            raise LocalStoreError(str(exc)) from exc
    if record_type == "work-events":
        try:
            return parse_work_event(payload).revision
        except ValueError as exc:
            raise LocalStoreError(str(exc)) from exc
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
        if record_type == "knowledge":
            has_capability_identity = bool(
                record_id.endswith("-capabilities")
                and information_record.subject_ref
                == f"project:{record_id.removesuffix('-capabilities')}/capabilities"
            )
            profile = information_record.payload.get("profile")
            if profile is not None and not has_capability_identity:
                raise LocalStoreError(
                    "structured project profile requires the capability record identity"
                )
            if profile is not None:
                from .project_capability_profile import (
                    parse_project_capability_profile,
                )

                try:
                    parsed_profile = parse_project_capability_profile(profile)
                except ValueError as exc:
                    raise LocalStoreError(str(exc)) from exc
                if parsed_profile["project_id"] != record_id.removesuffix(
                    "-capabilities"
                ):
                    raise LocalStoreError(
                        "structured project profile identity is inconsistent"
                    )
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

    @property
    def layout_version(self) -> int:
        try:
            return home_layout_version(self._data_root)
        except HomeLayoutError as exc:
            raise LocalStoreError(str(exc)) from exc

    def _legacy_target(self, record_type: str, record_id: str) -> Path:
        collection = COLLECTIONS.get(record_type)
        if collection is None:
            raise LocalStoreError("record type is invalid")
        if not IDENTIFIER.fullmatch(record_id):
            raise LocalStoreError("record id must be portable")
        return self._data_root.joinpath(*collection[1].split("/")) / f"{record_id}.json"

    def _v2_project_targets(
        self,
        record_type: str,
        record_id: str,
    ) -> tuple[Path, ...]:
        if record_type not in PROJECT_COLLECTION_PATHS:
            return ()
        projects_root = self._data_root / "projects"
        if not projects_root.is_dir() or projects_root.is_symlink():
            return ()
        if record_type in {"projects", "project-capsules"}:
            direct = collection_target(
                self._data_root,
                record_type,
                record_id,
                record_id,
            )
            return (direct,) if direct.exists() else ()
        targets = []
        for project_root in sorted(projects_root.iterdir()):
            if (
                project_root.is_symlink()
                or not project_root.is_dir()
                or not IDENTIFIER.fullmatch(project_root.name)
            ):
                continue
            target = collection_target(
                self._data_root,
                record_type,
                record_id,
                project_root.name,
            )
            if target.exists():
                targets.append(target)
        return tuple(targets)

    def _existing_targets(
        self,
        record_type: str,
        record_id: str,
    ) -> tuple[Path, ...]:
        candidates = []
        legacy = self._legacy_target(record_type, record_id)
        if legacy.exists():
            candidates.append(legacy)
        if self.layout_version >= 2:
            global_target = collection_target(
                self._data_root,
                record_type,
                record_id,
                None,
            )
            if global_target.exists() and global_target not in candidates:
                candidates.append(global_target)
            for target in self._v2_project_targets(record_type, record_id):
                if target not in candidates:
                    candidates.append(target)
        return tuple(candidates)

    @staticmethod
    def _subject_project_id(value: object) -> str | None:
        if not isinstance(value, str) or not value.startswith("project:"):
            return None
        project_id = value[len("project:") :].split("/", 1)[0]
        return project_id if IDENTIFIER.fullmatch(project_id) else None

    def _binding_project_id(self, binding_id: object) -> str | None:
        if not isinstance(binding_id, str) or not IDENTIFIER.fullmatch(binding_id):
            return None
        binding = self.read("source-bindings", binding_id)
        if binding is None:
            return None
        source_id = binding.payload.get("source_id")
        source_kind = binding.payload.get("source_kind")
        if (
            source_kind == "project"
            and isinstance(source_id, str)
            and IDENTIFIER.fullmatch(source_id)
        ):
            return source_id
        return None

    def _infer_project_id(
        self,
        record_type: str,
        record_id: str,
        payload: Mapping[str, object],
    ) -> str | None:
        if record_type in {"project-capsules", "projects", "project-integrations"}:
            return record_id
        explicit = payload.get("project_id")
        if isinstance(explicit, str) and IDENTIFIER.fullmatch(explicit):
            return explicit
        if record_type == "workspaces":
            project_refs = payload.get("project_refs")
            if (
                isinstance(project_refs, list)
                and len(project_refs) == 1
                and isinstance(project_refs[0], str)
                and IDENTIFIER.fullmatch(project_refs[0])
            ):
                return project_refs[0]
        if record_type == "source-bindings":
            source_id = payload.get("source_id")
            if (
                payload.get("source_kind") == "project"
                and isinstance(source_id, str)
                and IDENTIFIER.fullmatch(source_id)
            ):
                return source_id
        if record_type == "integrations":
            return self._binding_project_id(payload.get("source_binding_ref"))
        if record_type == "source-states":
            return self._binding_project_id(payload.get("binding_id"))
        subject_project = self._subject_project_id(payload.get("subject_ref"))
        if subject_project is not None:
            return subject_project
        information_payload = payload.get("payload")
        if isinstance(information_payload, Mapping):
            subject_project = self._subject_project_id(
                information_payload.get("subject_ref")
            )
            if subject_project is not None:
                return subject_project
        provenance = payload.get("provenance")
        if isinstance(provenance, Mapping):
            evidence = provenance.get("evidence")
            if isinstance(evidence, list):
                projects = set()
                for item in evidence:
                    if not isinstance(item, Mapping):
                        continue
                    source_ref = item.get("source_ref")
                    if isinstance(source_ref, str) and source_ref.startswith("source:"):
                        candidate = source_ref[len("source:") :].split("/", 1)[0]
                        if IDENTIFIER.fullmatch(candidate):
                            projects.add(candidate)
                if len(projects) == 1:
                    return next(iter(projects))
        return None

    def record_project_id(
        self,
        record_type: str,
        record_id: str,
        payload: Mapping[str, object],
    ) -> str | None:
        """Resolve one record's project scope without changing local state."""

        if record_type not in COLLECTIONS:
            raise LocalStoreError("record type is invalid")
        return self._infer_project_id(record_type, record_id, payload)

    def _target(self, record_type: str, record_id: str) -> Path:
        candidates = self._existing_targets(record_type, record_id)
        if len(candidates) > 1:
            raise LocalStoreError("record exists in multiple home layout locations")
        if candidates:
            return candidates[0]
        return self._legacy_target(record_type, record_id)

    def _planned_target(
        self,
        record_type: str,
        record_id: str,
        payload: Mapping[str, object],
        project_id: str | None,
    ) -> tuple[Path, str | None]:
        if self.layout_version < 2:
            return self._legacy_target(record_type, record_id), None
        inferred = self._infer_project_id(record_type, record_id, payload)
        if project_id is not None:
            if not IDENTIFIER.fullmatch(project_id):
                raise LocalStoreError("project id must be portable")
            if inferred is not None and inferred != project_id:
                raise LocalStoreError("record project scope conflicts with its payload")
            inferred = project_id
        existing = self._existing_targets(record_type, record_id)
        if len(existing) > 1:
            raise LocalStoreError("record exists in multiple home layout locations")
        if existing:
            target = existing[0]
            return target, inferred
        target = collection_target(
            self._data_root,
            record_type,
            record_id,
            inferred,
        )
        return target, inferred

    def _target_ref(self, target: Path) -> str:
        try:
            relative = target.relative_to(self._data_root).as_posix()
        except ValueError as exc:
            raise LocalStoreError("record target escaped the KRCN home") from exc
        return f".krcn/{relative}"

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

        if record_type not in COLLECTIONS:
            raise LocalStoreError("record type is invalid")
        record_ids = set()
        legacy_directory = self._legacy_target(record_type, "placeholder").parent
        if legacy_directory.exists():
            if legacy_directory.is_symlink() or not legacy_directory.is_dir():
                raise LocalStoreError("record collection must be a regular directory")
            record_ids.update(path.stem for path in legacy_directory.glob("*.json"))
        if self.layout_version >= 2:
            global_directory = collection_target(
                self._data_root,
                record_type,
                "placeholder",
                None,
            ).parent
            if global_directory.exists():
                if global_directory.is_symlink() or not global_directory.is_dir():
                    raise LocalStoreError("global record collection must be regular")
                record_ids.update(path.stem for path in global_directory.glob("*.json"))
            projects_root = self._data_root / "projects"
            if projects_root.exists():
                if projects_root.is_symlink() or not projects_root.is_dir():
                    raise LocalStoreError("project capsule root must be regular")
                for project_root in sorted(projects_root.iterdir()):
                    if (
                        project_root.is_symlink()
                        or not project_root.is_dir()
                        or not IDENTIFIER.fullmatch(project_root.name)
                    ):
                        continue
                    if record_type in {"projects", "project-capsules"}:
                        candidate = collection_target(
                            self._data_root,
                            record_type,
                            project_root.name,
                            project_root.name,
                        )
                        if candidate.exists():
                            record_ids.add(project_root.name)
                    else:
                        directory = collection_target(
                            self._data_root,
                            record_type,
                            "placeholder",
                            project_root.name,
                        ).parent
                        if directory.exists():
                            if directory.is_symlink() or not directory.is_dir():
                                raise LocalStoreError(
                                    "project record collection must be regular"
                                )
                            record_ids.update(
                                path.stem for path in directory.glob("*.json")
                            )
        records: list[StoredRecord] = []
        for record_id in sorted(record_ids):
            record = self.read(record_type, record_id)
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
        project_id: str | None = None,
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
        target, scoped_project_id = self._planned_target(
            record_type,
            record_id,
            payload_copy,
            project_id,
        )
        mutation = plan_mutation(
            self._ownership,
            operation="create" if current is None else "update",
            target_ref=self._target_ref(target),
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
            target=target,
            layout_version=self.layout_version,
            project_id=scoped_project_id,
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
        target = plan.target
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

        if self.layout_version != plan.layout_version:
            raise RevisionConflictError("home layout changed after planning")
        current = self.read(plan.record_type, plan.record_id)
        current_revision = current.revision if current else 0
        if current_revision != plan.previous_revision:
            raise RevisionConflictError("record revision changed after planning")
        if current is not None and self._target(plan.record_type, plan.record_id) != plan.target:
            raise RevisionConflictError("record location changed after planning")

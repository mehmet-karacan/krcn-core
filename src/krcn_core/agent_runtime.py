"""Project-scoped transactional agent queue, leases, fencing, and recovery."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, TYPE_CHECKING

from .foundation import load_json
from .effect_ledger import parse_effect_claim, parse_effect_receipt
from .effect_ledger_store import EffectLedgerStore, effect_ledger_path
from .home_layout import project_capsule_root
from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, plan_mutation
from .work_graph import (
    ACTIVE_STATUSES,
    parse_work_item,
    work_graph_projection_is_current,
)

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore
    from .mutation_gate import OwnershipResolver


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SIDE_EFFECTS = {"read", "write", "execute", "network"}
ROLES = {"worker", "verifier"}
TERMINAL = {"completed", "failed", "blocked", "recovery-required"}
EMPTY_STATE_DIGEST = hashlib.sha256(b"krcn-empty-runtime-queue-v1").hexdigest()


class AgentRuntimeError(ValueError):
    """Raised when queue ownership, lease, or fencing evidence is invalid."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _owner_digest(token: object) -> str:
    if not isinstance(token, str) or len(token) < 16:
        raise AgentRuntimeError("owner token must contain at least 16 characters")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def runtime_queue_path(data_root: Path, project_id: str) -> Path:
    if not IDENTIFIER.fullmatch(project_id):
        raise AgentRuntimeError("runtime project id is invalid")
    return project_capsule_root(data_root, project_id) / "runtime" / "queue" / "scheduler-v1.sqlite"


def _resource_ref(value: object, project_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentRuntimeError("runtime resource ref is required")
    if value == f"project:{project_id}":
        return value
    task_prefix = f"task:{project_id}:"
    if value.startswith(task_prefix) and IDENTIFIER.fullmatch(value[len(task_prefix):]):
        return value
    path_prefix = f"path:{project_id}:"
    if value.startswith(path_prefix):
        relative = value[len(path_prefix):]
        path = PurePosixPath(relative)
        if relative and not path.is_absolute() and ".." not in path.parts and "\\" not in relative:
            return f"{path_prefix}{path.as_posix()}"
    raise AgentRuntimeError("runtime resource ref is not portable")


def validate_runtime_resource_ref(value: object, project_id: str) -> str:
    """Return one canonical project-scoped resource reference."""

    return _resource_ref(value, project_id)


def _resource_conflicts(left: str, right: str) -> bool:
    if left == right:
        return True
    left_prefix = left.split(":", 1)
    right_prefix = right.split(":", 1)
    if len(left_prefix) == 2 and len(right_prefix) == 2:
        if left_prefix[0] == "project" and (
            right == left or right.startswith(f"task:{left_prefix[1]}:")
            or right.startswith(f"path:{left_prefix[1]}:")
        ):
            return True
        if right_prefix[0] == "project" and (
            left == right or left.startswith(f"task:{right_prefix[1]}:")
            or left.startswith(f"path:{right_prefix[1]}:")
        ):
            return True
    left_parts = left.split(":", 2)
    right_parts = right.split(":", 2)
    if len(left_parts) != 3 or len(right_parts) != 3 or left_parts[:2] != right_parts[:2]:
        return False
    if left_parts[0] != "path":
        return False
    left_path = PurePosixPath(left_parts[2])
    right_path = PurePosixPath(right_parts[2])
    return left_path in right_path.parents or right_path in left_path.parents


def runtime_resource_refs_conflict(left: str, right: str) -> bool:
    """Report whether two canonical runtime resource references overlap."""

    return _resource_conflicts(left, right)


@dataclass(frozen=True)
class SchedulerPolicy:
    default_lease_seconds: int
    minimum_lease_seconds: int
    maximum_lease_seconds: int
    heartbeat_interval_seconds: int
    default_max_attempts: int
    maximum_attempts: int
    claim_busy_timeout_ms: int


def load_scheduler_policy(repo_root: Path) -> SchedulerPolicy:
    payload = load_json(repo_root / "config" / "runtime-scheduler.json")
    expected = {
        "schema_ref", "schema_version", "database_schema_version",
        "default_lease_seconds", "minimum_lease_seconds",
        "maximum_lease_seconds", "heartbeat_interval_seconds",
        "default_max_attempts", "maximum_attempts", "claim_busy_timeout_ms",
        "automatic_replay_side_effects",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise AgentRuntimeError("runtime scheduler policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/runtime-scheduler-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("database_schema_version") != 2
        or payload.get("automatic_replay_side_effects") != ["read"]
    ):
        raise AgentRuntimeError("runtime scheduler policy is invalid")
    values = [
        payload[name] for name in (
            "default_lease_seconds", "minimum_lease_seconds",
            "maximum_lease_seconds", "heartbeat_interval_seconds",
            "default_max_attempts", "maximum_attempts", "claim_busy_timeout_ms",
        )
    ]
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values):
        raise AgentRuntimeError("runtime scheduler policy number is invalid")
    if not payload["minimum_lease_seconds"] <= payload["default_lease_seconds"] <= payload["maximum_lease_seconds"]:
        raise AgentRuntimeError("runtime scheduler lease bounds are invalid")
    if payload["default_max_attempts"] > payload["maximum_attempts"]:
        raise AgentRuntimeError("runtime scheduler attempt bounds are invalid")
    return SchedulerPolicy(*values)


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS queue_items(
  queue_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  work_item_id TEXT NOT NULL,
  work_item_revision INTEGER NOT NULL,
  work_item_digest TEXT NOT NULL,
  task_id TEXT NOT NULL,
  parent_task_id TEXT,
  plan_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  required_role TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  side_effects_json TEXT NOT NULL,
  resources_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL,
  current_fence INTEGER NOT NULL,
  result_digest TEXT,
  ledger_required INTEGER NOT NULL DEFAULT 0,
  validation_gate_id TEXT,
  effect_claim_id TEXT,
  effect_receipt_id TEXT
);
CREATE TABLE IF NOT EXISTS leases(
  lease_id TEXT PRIMARY KEY,
  queue_id TEXT NOT NULL UNIQUE,
  owner_digest TEXT NOT NULL,
  fencing_token INTEGER NOT NULL,
  issued_at REAL NOT NULL,
  heartbeat_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_locks(
  resource_ref TEXT PRIMARY KEY,
  queue_id TEXT NOT NULL,
  lease_id TEXT NOT NULL,
  fencing_token INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts(
  attempt_id TEXT PRIMARY KEY,
  queue_id TEXT NOT NULL,
  attempt_number INTEGER NOT NULL,
  fencing_token INTEGER NOT NULL,
  status TEXT NOT NULL,
  started_at REAL NOT NULL,
  finished_at REAL,
  evidence_digest TEXT,
  UNIQUE(queue_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS scheduler_events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  queue_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  fencing_token INTEGER,
  observed_at REAL NOT NULL,
  evidence_digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projection_jobs(
  job_id TEXT PRIMARY KEY,
  queue_id TEXT NOT NULL UNIQUE,
  project_id TEXT NOT NULL,
  work_item_id TEXT NOT NULL,
  work_item_revision INTEGER NOT NULL,
  work_item_digest TEXT NOT NULL,
  status TEXT NOT NULL
);
"""


class AgentRuntimeQueue:
    """Use one SQLite transaction boundary for ownership and completion state."""

    def __init__(
        self,
        data_root: Path,
        project_id: str,
        policy: SchedulerPolicy,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.data_root = data_root.resolve()
        self.project_id = project_id
        self.path = runtime_queue_path(self.data_root, project_id)
        self.policy = policy
        self.clock = clock

    def _connect(self, create: bool) -> sqlite3.Connection | None:
        if not self.path.exists() and not create:
            return None
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=self.policy.claim_busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.policy.claim_busy_timeout_ms}")
        if create:
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO metadata VALUES('schema_version','2')")
            connection.commit()
        version = connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if version is None or version[0] not in {"1", "2"}:
            connection.close()
            raise AgentRuntimeError("runtime queue schema version is invalid")
        return connection

    @staticmethod
    def _state_payload(connection: sqlite3.Connection) -> dict[str, object]:
        tables = (
            "queue_items", "leases", "resource_locks", "attempts",
            "scheduler_events", "projection_jobs",
        )
        payload = {}
        for table in tables:
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
            payload[table] = {"columns": columns, "rows": rows}
        return payload

    def state_digest(self) -> str:
        connection = self._connect(create=False)
        if connection is None:
            return EMPTY_STATE_DIGEST
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AgentRuntimeError("runtime queue integrity check failed")
            return _digest(self._state_payload(connection))
        finally:
            connection.close()

    def _begin(self, expected_state_digest: str, *, allow_legacy: bool = False) -> sqlite3.Connection:
        connection = self._connect(create=True)
        assert connection is not None
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version is None or (version[0] == "1" and not allow_legacy):
            connection.rollback()
            connection.close()
            raise AgentRuntimeError("runtime queue v1 requires explicit additive migration")
        current = _digest(self._state_payload(connection))
        expected = (
            _digest(self._state_payload(connection))
            if expected_state_digest == EMPTY_STATE_DIGEST and not any(
                connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                for table in ("queue_items", "leases", "attempts", "scheduler_events", "projection_jobs")
            )
            else expected_state_digest
        )
        if current != expected:
            connection.rollback()
            connection.close()
            raise AgentRuntimeError("runtime queue changed after planning")
        return connection

    @staticmethod
    def _event(connection: sqlite3.Connection, queue_id: str, kind: str, fence: int | None, now: float, evidence: str) -> None:
        connection.execute(
            "INSERT INTO scheduler_events(queue_id,event_type,fencing_token,observed_at,evidence_digest) VALUES(?,?,?,?,?)",
            (queue_id, kind, fence, now, evidence),
        )

    def apply(self, action: str, arguments: Mapping[str, object], expected_state_digest: str) -> dict[str, object]:
        method = getattr(self, f"_apply_{action}", None)
        if method is None:
            raise AgentRuntimeError("runtime queue action is invalid")
        connection = self._begin(expected_state_digest, allow_legacy=action == "migrate_v2")
        try:
            result = method(connection, arguments)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _apply_enqueue(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        existing = connection.execute(
            "SELECT queue_id,status FROM queue_items WHERE idempotency_key=?",
            (arguments["idempotency_key"],),
        ).fetchone()
        if existing:
            return {"queue_id": existing["queue_id"], "status": existing["status"], "idempotent_reuse": True}
        connection.execute(
            "INSERT INTO queue_items(queue_id,project_id,work_item_id,work_item_revision,work_item_digest,task_id,parent_task_id,plan_id,step_id,required_role,capabilities_json,side_effects_json,resources_json,idempotency_key,status,attempts,max_attempts,current_fence,result_digest,ledger_required,validation_gate_id,effect_claim_id,effect_receipt_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                arguments["queue_id"], self.project_id, arguments["work_item_id"],
                arguments["work_item_revision"], arguments["work_item_digest"],
                arguments["task_id"], arguments["parent_task_id"], arguments["plan_id"],
                arguments["step_id"], arguments["required_role"],
                json.dumps(arguments["required_capabilities"], separators=(",", ":")),
                json.dumps(arguments["side_effects"], separators=(",", ":")),
                json.dumps(arguments["resource_refs"], separators=(",", ":")),
                arguments["idempotency_key"], "queued", 0, arguments["max_attempts"], 0, None,
                1 if arguments.get("validation_gate_id") is not None else 0,
                arguments.get("validation_gate_id"), None, None,
            ),
        )
        now = self.clock()
        self._event(connection, str(arguments["queue_id"]), "enqueued", None, now, str(arguments["idempotency_key"]))
        return {"queue_id": arguments["queue_id"], "status": "queued", "idempotent_reuse": False}

    def _apply_migrate_v2(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version is None:
            raise AgentRuntimeError("runtime queue schema metadata is missing")
        if version[0] == "2":
            return {"status": "current", "from_version": 2, "to_version": 2, "migrated": False}
        if version[0] != "1":
            raise AgentRuntimeError("runtime queue schema version is invalid")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(queue_items)")}
        additions = (
            ("ledger_required", "INTEGER NOT NULL DEFAULT 0"),
            ("validation_gate_id", "TEXT"),
            ("effect_claim_id", "TEXT"),
            ("effect_receipt_id", "TEXT"),
        )
        for name, declaration in additions:
            if name not in columns:
                connection.execute(f"ALTER TABLE queue_items ADD COLUMN {name} {declaration}")
        connection.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
        self._event(connection, "queue-migration", "schema-migrated", None, self.clock(), _digest({"from": 1, "to": 2}))
        return {"status": "migrated", "from_version": 1, "to_version": 2, "migrated": True}

    def _apply_claim(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        now = self.clock()
        capabilities = set(arguments["capability_refs"])
        rows = connection.execute(
            "SELECT * FROM queue_items WHERE status='queued' AND required_role=? ORDER BY queue_id",
            (arguments["worker_role"],),
        ).fetchall()
        selected = None
        for row in rows:
            if not set(json.loads(row["capabilities_json"])).issubset(capabilities):
                continue
            resources = json.loads(row["resources_json"])
            locks = [value[0] for value in connection.execute("SELECT resource_ref FROM resource_locks")]
            if any(_resource_conflicts(resource, locked) for resource in resources for locked in locks):
                continue
            selected = row
            break
        if selected is None:
            return {"claimed": False, "queue_id": None}
        fence = int(selected["current_fence"]) + 1
        attempt = int(selected["attempts"]) + 1
        identity = {
            "queue_id": selected["queue_id"], "fence": fence,
            "owner_digest": arguments["owner_digest"], "attempt": attempt,
        }
        lease_id = "lease-" + _digest(identity)[:24]
        attempt_id = "attempt-" + _digest({**identity, "lease_id": lease_id})[:24]
        expires = now + int(arguments["lease_seconds"])
        connection.execute(
            "UPDATE queue_items SET status='leased',attempts=?,current_fence=? WHERE queue_id=?",
            (attempt, fence, selected["queue_id"]),
        )
        connection.execute(
            "INSERT INTO leases VALUES(?,?,?,?,?,?,?)",
            (lease_id, selected["queue_id"], arguments["owner_digest"], fence, now, now, expires),
        )
        connection.execute(
            "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",
            (attempt_id, selected["queue_id"], attempt, fence, "executing", now, None, None),
        )
        for resource in json.loads(selected["resources_json"]):
            connection.execute(
                "INSERT INTO resource_locks VALUES(?,?,?,?)",
                (resource, selected["queue_id"], lease_id, fence),
            )
        self._event(connection, selected["queue_id"], "claimed", fence, now, _digest(identity))
        return {
            "claimed": True,
            "queue_id": selected["queue_id"],
            "lease_id": lease_id,
            "fencing_token": fence,
            "attempt_id": attempt_id,
            "expires_at": expires,
            "ledger_required": bool(selected["ledger_required"]),
            "validation_gate_id": selected["validation_gate_id"],
        }

    @staticmethod
    def _lease(connection: sqlite3.Connection, arguments: Mapping[str, object], now: float) -> sqlite3.Row:
        lease = connection.execute(
            "SELECT * FROM leases WHERE lease_id=? AND queue_id=?",
            (arguments["lease_id"], arguments["queue_id"]),
        ).fetchone()
        if (
            lease is None
            or lease["owner_digest"] != arguments["owner_digest"]
            or lease["fencing_token"] != arguments["fencing_token"]
            or lease["expires_at"] <= now
        ):
            raise AgentRuntimeError("runtime lease ownership or fencing evidence is stale")
        return lease

    def _apply_heartbeat(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        now = self.clock()
        lease = self._lease(connection, arguments, now)
        expires = now + int(arguments["lease_seconds"])
        connection.execute(
            "UPDATE leases SET heartbeat_at=?,expires_at=? WHERE lease_id=?",
            (now, expires, lease["lease_id"]),
        )
        self._event(connection, lease["queue_id"], "heartbeat", lease["fencing_token"], now, _digest({"expires": expires}))
        return {"queue_id": lease["queue_id"], "lease_id": lease["lease_id"], "fencing_token": lease["fencing_token"], "expires_at": expires}

    def _apply_bind_effect_claim(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        lease = self._lease(connection, arguments, self.clock())
        queue = connection.execute("SELECT * FROM queue_items WHERE queue_id=?", (lease["queue_id"],)).fetchone()
        if queue is None or queue["status"] != "leased" or not queue["ledger_required"]:
            raise AgentRuntimeError("runtime queue item does not require an effect ledger")
        if queue["validation_gate_id"] != arguments["validation_gate_id"]:
            raise AgentRuntimeError("runtime validation gate binding changed")
        current = queue["effect_claim_id"]
        if current is not None and current != arguments["effect_claim_id"]:
            raise AgentRuntimeError("runtime queue item already has a conflicting effect claim")
        connection.execute(
            "UPDATE queue_items SET effect_claim_id=? WHERE queue_id=?",
            (arguments["effect_claim_id"], lease["queue_id"]),
        )
        self._event(connection, lease["queue_id"], "effect-claimed", lease["fencing_token"], self.clock(), arguments["effect_claim_id"])
        return {"queue_id": lease["queue_id"], "effect_claim_id": arguments["effect_claim_id"], "idempotent_reuse": current is not None}

    def _apply_bind_effect_receipt(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        lease = self._lease(connection, arguments, self.clock())
        queue = connection.execute("SELECT * FROM queue_items WHERE queue_id=?", (lease["queue_id"],)).fetchone()
        if queue is None or queue["status"] != "leased" or queue["effect_claim_id"] != arguments["effect_claim_id"]:
            raise AgentRuntimeError("runtime effect receipt has no matching claim")
        current = queue["effect_receipt_id"]
        if current is not None and current != arguments["effect_receipt_id"]:
            raise AgentRuntimeError("runtime queue item already has a conflicting effect receipt")
        connection.execute(
            "UPDATE queue_items SET effect_receipt_id=? WHERE queue_id=?",
            (arguments["effect_receipt_id"], lease["queue_id"]),
        )
        self._event(connection, lease["queue_id"], "effect-receipted", lease["fencing_token"], self.clock(), arguments["effect_receipt_id"])
        return {"queue_id": lease["queue_id"], "effect_receipt_id": arguments["effect_receipt_id"], "idempotent_reuse": current is not None}

    def _finish(self, connection: sqlite3.Connection, arguments: Mapping[str, object], status: str) -> dict[str, object]:
        now = self.clock()
        lease = self._lease(connection, arguments, now)
        evidence = str(arguments["evidence_digest"])
        queue = connection.execute("SELECT * FROM queue_items WHERE queue_id=?", (lease["queue_id"],)).fetchone()
        if queue is None or queue["status"] != "leased":
            raise AgentRuntimeError("runtime queue item is not leased")
        if status == "completed" and queue["ledger_required"] and (
            queue["effect_claim_id"] is None or queue["effect_receipt_id"] is None
        ):
            raise AgentRuntimeError("runtime effect ledger receipt is required before completion")
        next_status = status
        if status == "failed":
            effects = set(json.loads(queue["side_effects_json"]))
            if arguments.get("replay_safe") is True and effects.issubset({"read"}) and queue["attempts"] < queue["max_attempts"]:
                next_status = "queued"
            elif queue["attempts"] >= queue["max_attempts"]:
                next_status = "blocked"
            else:
                next_status = "recovery-required"
        connection.execute(
            "UPDATE queue_items SET status=?,result_digest=? WHERE queue_id=?",
            (next_status, evidence, lease["queue_id"]),
        )
        connection.execute(
            "UPDATE attempts SET status=?,finished_at=?,evidence_digest=? WHERE queue_id=? AND fencing_token=?",
            (status, now, evidence, lease["queue_id"], lease["fencing_token"]),
        )
        connection.execute("DELETE FROM resource_locks WHERE lease_id=?", (lease["lease_id"],))
        connection.execute("DELETE FROM leases WHERE lease_id=?", (lease["lease_id"],))
        if status == "completed":
            job_id = "projection-" + _digest({"queue_id": queue["queue_id"], "work_digest": queue["work_item_digest"]})[:24]
            connection.execute(
                "INSERT OR IGNORE INTO projection_jobs VALUES(?,?,?,?,?,?,?)",
                (job_id, queue["queue_id"], self.project_id, queue["work_item_id"], queue["work_item_revision"], queue["work_item_digest"], "pending"),
            )
        self._event(connection, lease["queue_id"], status, lease["fencing_token"], now, evidence)
        return {"queue_id": lease["queue_id"], "status": next_status, "fencing_token": lease["fencing_token"], "projection_job_created": status == "completed"}

    def _apply_complete(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        return self._finish(connection, arguments, "completed")

    def _apply_fail(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        return self._finish(connection, arguments, "failed")

    def _apply_recover(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        now = self.clock()
        recovered = []
        for lease in connection.execute("SELECT * FROM leases WHERE expires_at<=? ORDER BY queue_id", (now,)).fetchall():
            queue = connection.execute("SELECT * FROM queue_items WHERE queue_id=?", (lease["queue_id"],)).fetchone()
            if queue is None:
                raise AgentRuntimeError("expired lease queue item is missing")
            effects = set(json.loads(queue["side_effects_json"]))
            if effects.issubset({"read"}) and queue["attempts"] < queue["max_attempts"]:
                status = "queued"
            elif queue["attempts"] >= queue["max_attempts"]:
                status = "blocked"
            else:
                status = "recovery-required"
            connection.execute("UPDATE queue_items SET status=? WHERE queue_id=?", (status, queue["queue_id"]))
            connection.execute(
                "UPDATE attempts SET status='expired',finished_at=? WHERE queue_id=? AND fencing_token=?",
                (now, queue["queue_id"], lease["fencing_token"]),
            )
            connection.execute("DELETE FROM resource_locks WHERE lease_id=?", (lease["lease_id"],))
            connection.execute("DELETE FROM leases WHERE lease_id=?", (lease["lease_id"],))
            evidence = _digest({"lease_id": lease["lease_id"], "expired_at": lease["expires_at"]})
            self._event(connection, queue["queue_id"], "lease-expired", lease["fencing_token"], now, evidence)
            recovered.append({"queue_id": queue["queue_id"], "status": status})
        return {"recovered_count": len(recovered), "items": recovered}

    def _apply_reconcile(self, connection: sqlite3.Connection, arguments: Mapping[str, object]) -> dict[str, object]:
        updates = arguments.get("projection_updates")
        if not isinstance(updates, list):
            raise AgentRuntimeError("runtime projection updates are invalid")
        completed = 0
        blocked = 0
        for update in updates:
            if not isinstance(update, dict) or set(update) != {"job_id", "status"}:
                raise AgentRuntimeError("runtime projection update is invalid")
            if update["status"] not in {"completed", "blocked-awaiting-work-graph-update"}:
                raise AgentRuntimeError("runtime projection status is invalid")
            changed = connection.execute(
                "UPDATE projection_jobs SET status=? WHERE job_id=? AND status IN ('pending','blocked-awaiting-work-graph-update')",
                (update["status"], update["job_id"]),
            ).rowcount
            if changed:
                completed += update["status"] == "completed"
                blocked += update["status"] != "completed"
        return {
            "updated_count": completed + blocked,
            "completed_count": completed,
            "blocked_count": blocked,
        }

    def projection_jobs(self) -> tuple[dict[str, object], ...]:
        connection = self._connect(create=False)
        if connection is None:
            return ()
        try:
            return tuple(
                dict(row) for row in connection.execute(
                    "SELECT * FROM projection_jobs WHERE status IN ('pending','blocked-awaiting-work-graph-update') ORDER BY job_id"
                )
            )
        finally:
            connection.close()

    def status(self) -> dict[str, object]:
        connection = self._connect(create=False)
        if connection is None:
            return {"project_id": self.project_id, "items": [], "counts": {}, "active_lease_count": 0, "integrity_verified": True, "paths_disclosed": False}
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AgentRuntimeError("runtime queue integrity check failed")
            queue_columns = {row[1] for row in connection.execute("PRAGMA table_info(queue_items)")}
            effect_columns = "ledger_required,validation_gate_id,effect_claim_id,effect_receipt_id" if "ledger_required" in queue_columns else "0 AS ledger_required,NULL AS validation_gate_id,NULL AS effect_claim_id,NULL AS effect_receipt_id"
            items = [dict(row) for row in connection.execute(
                f"SELECT queue_id,work_item_id,work_item_revision,work_item_digest,task_id,plan_id,step_id,required_role,status,attempts,max_attempts,current_fence,result_digest,{effect_columns} FROM queue_items ORDER BY queue_id"
            )]
            counts = {row["status"]: row["count"] for row in connection.execute("SELECT status,COUNT(*) AS count FROM queue_items GROUP BY status")}
            active = connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
            pending = connection.execute("SELECT COUNT(*) FROM projection_jobs WHERE status IN ('pending','blocked-awaiting-work-graph-update')").fetchone()[0]
            completed_projections = connection.execute("SELECT COUNT(*) FROM projection_jobs WHERE status='completed'").fetchone()[0]
            return {"project_id": self.project_id, "items": items, "counts": counts, "active_lease_count": active, "pending_projection_count": pending, "completed_projection_count": completed_projections, "integrity_verified": True, "paths_disclosed": False}
        finally:
            connection.close()


@dataclass(frozen=True)
class RuntimeQueuePlan:
    project_id: str
    action: str
    arguments: Mapping[str, object]
    state_digest: str
    plan_id: str
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/runtime-queue-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "action": self.action,
            "state_digest": self.state_digest,
            "owner_token_stored": False,
            "source_content_included": False,
            "mutation": self.mutation.as_dict(),
        }


def _identifiers(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or len(set(value)) != len(value) or any(
        not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in value
    ):
        raise AgentRuntimeError(f"{label} must contain portable identifiers")
    return sorted(value)


def prepare_runtime_queue_action(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    action: str,
    arguments: Mapping[str, object],
    *,
    clock: Callable[[], float] = time.time,
) -> tuple[AgentRuntimeQueue, RuntimeQueuePlan]:
    allowed_actions = {"migrate_v2", "enqueue", "claim", "heartbeat", "bind_effect_claim", "bind_effect_receipt", "complete", "fail", "recover", "reconcile"}
    if action not in allowed_actions:
        raise AgentRuntimeError("runtime queue action is invalid")
    project_id = arguments.get("project_id")
    if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id) or store.read("projects", project_id) is None:
        raise AgentRuntimeError("runtime queue project is not registered")
    policy = load_scheduler_policy(repo_root)
    queue = AgentRuntimeQueue(store.data_root, project_id, policy, clock=clock)
    sanitized: dict[str, object] = {"project_id": project_id}
    if action == "migrate_v2":
        if set(arguments) != {"project_id"}:
            raise AgentRuntimeError("runtime queue migration fields are invalid")
    elif action == "enqueue":
        required = {"project_id", "work_item_id", "task_id", "plan_id", "step_id", "required_role", "required_capabilities", "side_effects", "resource_refs"}
        optional = {"parent_task_id", "max_attempts", "validation_gate_id"}
        if set(arguments) - required - optional or not required.issubset(arguments):
            raise AgentRuntimeError("runtime enqueue fields are invalid")
        work_id = arguments.get("work_item_id")
        work_record = store.read("work-items", str(work_id))
        if work_record is None:
            raise AgentRuntimeError("runtime work item was not found")
        work = parse_work_item(work_record.payload)
        if work.project_id != project_id or work.status not in ACTIVE_STATUSES:
            raise AgentRuntimeError("runtime work item is not active in this project")
        for relation in work.relations:
            if relation.relation_type != "depends-on":
                continue
            dependency_record = store.read("work-items", relation.target_ref)
            if dependency_record is None or parse_work_item(dependency_record.payload).status != "completed":
                raise AgentRuntimeError("runtime work dependency is not completed")
        for field in ("task_id", "step_id"):
            value = arguments.get(field)
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise AgentRuntimeError("runtime task or step id is invalid")
        plan_id = arguments.get("plan_id")
        if not isinstance(plan_id, str) or not SHA256.fullmatch(plan_id):
            raise AgentRuntimeError("runtime plan id is invalid")
        parent = arguments.get("parent_task_id")
        if parent is not None and (not isinstance(parent, str) or not IDENTIFIER.fullmatch(parent)):
            raise AgentRuntimeError("runtime parent task id is invalid")
        role = arguments.get("required_role")
        if role not in ROLES:
            raise AgentRuntimeError("runtime role is invalid")
        capabilities = _identifiers(arguments.get("required_capabilities"), "runtime capabilities")
        effects = arguments.get("side_effects")
        if not isinstance(effects, list) or len(set(effects)) != len(effects) or not set(effects).issubset(SIDE_EFFECTS):
            raise AgentRuntimeError("runtime side effects are invalid")
        if role == "verifier" and not set(effects).issubset({"read", "execute"}):
            raise AgentRuntimeError("verifier queue item may only read or execute")
        validation_gate_id = arguments.get("validation_gate_id")
        if validation_gate_id is not None and (not isinstance(validation_gate_id, str) or not SHA256.fullmatch(validation_gate_id)):
            raise AgentRuntimeError("runtime validation gate id is invalid")
        if validation_gate_id is not None and set(effects).issubset({"read"}):
            raise AgentRuntimeError("read-only runtime step may not require an effect ledger")
        resources_value = arguments.get("resource_refs")
        if not isinstance(resources_value, list) or len(set(resources_value)) != len(resources_value):
            raise AgentRuntimeError("runtime resources are invalid")
        resources = sorted(_resource_ref(value, project_id) for value in resources_value)
        max_attempts = arguments.get("max_attempts", policy.default_max_attempts)
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= policy.maximum_attempts:
            raise AgentRuntimeError("runtime maximum attempts is invalid")
        identity = {
            "project_id": project_id, "work_item_id": work.work_item_id,
            "work_item_revision": work.revision, "work_item_digest": work.work_digest,
            "task_id": arguments["task_id"], "parent_task_id": parent,
            "plan_id": plan_id, "step_id": arguments["step_id"],
            "required_role": role, "required_capabilities": capabilities,
            "side_effects": sorted(effects), "resource_refs": resources,
        }
        if validation_gate_id is not None:
            identity["validation_gate_id"] = validation_gate_id
        idempotency = _digest(identity)
        sanitized.update(identity)
        sanitized.update({"idempotency_key": idempotency, "queue_id": "queue-" + idempotency[:24], "max_attempts": max_attempts})
    elif action == "claim":
        required = {"project_id", "owner_token", "worker_role", "capability_refs"}
        if set(arguments) - required - {"lease_seconds"} or not required.issubset(arguments):
            raise AgentRuntimeError("runtime claim fields are invalid")
        role = arguments.get("worker_role")
        if role not in ROLES:
            raise AgentRuntimeError("runtime worker role is invalid")
        lease_seconds = arguments.get("lease_seconds", policy.default_lease_seconds)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not policy.minimum_lease_seconds <= lease_seconds <= policy.maximum_lease_seconds:
            raise AgentRuntimeError("runtime lease duration is invalid")
        sanitized.update({"owner_digest": _owner_digest(arguments.get("owner_token")), "worker_role": role, "capability_refs": _identifiers(arguments.get("capability_refs"), "runtime claim capabilities"), "lease_seconds": lease_seconds})
    elif action in {"heartbeat", "bind_effect_claim", "bind_effect_receipt", "complete", "fail"}:
        required = {"project_id", "queue_id", "lease_id", "owner_token", "fencing_token"}
        if action == "heartbeat":
            optional = {"lease_seconds"}
        elif action == "bind_effect_claim":
            optional = {"effect_claim"}
        elif action == "bind_effect_receipt":
            optional = {"effect_receipt"}
        else:
            optional = {"evidence_digest", "replay_safe"} if action == "fail" else {"evidence_digest"}
        if set(arguments) - required - optional or not required.issubset(arguments):
            raise AgentRuntimeError("runtime lease action fields are invalid")
        for field in ("queue_id", "lease_id"):
            if not isinstance(arguments.get(field), str) or not IDENTIFIER.fullmatch(str(arguments[field])):
                raise AgentRuntimeError("runtime lease action identity is invalid")
        fence = arguments.get("fencing_token")
        if not isinstance(fence, int) or isinstance(fence, bool) or fence < 1:
            raise AgentRuntimeError("runtime fencing token is invalid")
        sanitized.update({"queue_id": arguments["queue_id"], "lease_id": arguments["lease_id"], "owner_digest": _owner_digest(arguments.get("owner_token")), "fencing_token": fence})
        if action == "heartbeat":
            lease_seconds = arguments.get("lease_seconds", policy.default_lease_seconds)
            if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not policy.minimum_lease_seconds <= lease_seconds <= policy.maximum_lease_seconds:
                raise AgentRuntimeError("runtime heartbeat duration is invalid")
            sanitized["lease_seconds"] = lease_seconds
        elif action in {"bind_effect_claim", "bind_effect_receipt"}:
            ledger_path = effect_ledger_path(store.data_root, project_id)
            if not ledger_path.is_file():
                raise AgentRuntimeError("runtime durable effect ledger is unavailable")
            ledger = EffectLedgerStore(ledger_path)
            if action == "bind_effect_claim":
                try:
                    effect_claim = parse_effect_claim(arguments.get("effect_claim"))
                except ValueError as exc:
                    raise AgentRuntimeError("runtime effect claim is invalid") from exc
                status = ledger.claim_status(effect_claim.claim_id)
                binding = effect_claim.payload["bindings"]
                if (
                    not status.get("found")
                    or status.get("project_id") != project_id
                    or status.get("queue_id") != arguments["queue_id"]
                    or status.get("lease_id") != arguments["lease_id"]
                    or status.get("fencing_token") != fence
                    or binding["attempt_id"] != status.get("attempt_id")
                ):
                    raise AgentRuntimeError("runtime effect claim is not durable or does not match lease")
                sanitized["validation_gate_id"] = effect_claim.payload["validation_gate_id"]
                sanitized["effect_claim_id"] = effect_claim.claim_id
            else:
                try:
                    effect_receipt = parse_effect_receipt(arguments.get("effect_receipt"))
                except ValueError as exc:
                    raise AgentRuntimeError("runtime effect receipt is invalid") from exc
                status = ledger.claim_status(str(effect_receipt.payload["claim_id"]))
                if (
                    status.get("receipt_id") != effect_receipt.receipt_id
                    or status.get("receipt_status") != "completed"
                    or status.get("project_id") != project_id
                    or status.get("queue_id") != arguments["queue_id"]
                    or status.get("lease_id") != arguments["lease_id"]
                    or status.get("fencing_token") != fence
                ):
                    raise AgentRuntimeError("runtime completed effect receipt is not durable or does not match lease")
                sanitized["effect_claim_id"] = effect_receipt.payload["claim_id"]
                sanitized["effect_receipt_id"] = effect_receipt.receipt_id
        else:
            evidence = arguments.get("evidence_digest")
            if not isinstance(evidence, str) or not SHA256.fullmatch(evidence):
                raise AgentRuntimeError("runtime completion evidence is invalid")
            sanitized["evidence_digest"] = evidence
            if action == "fail":
                sanitized["replay_safe"] = arguments.get("replay_safe", False) is True
    elif action == "recover":
        if set(arguments) != {"project_id"}:
            raise AgentRuntimeError("runtime recovery fields are invalid")
    elif action == "reconcile":
        if set(arguments) != {"project_id"}:
            raise AgentRuntimeError("runtime reconciliation fields are invalid")
        updates = []
        projection_current = work_graph_projection_is_current(store, project_id)
        for job in queue.projection_jobs():
            work_record = store.read("work-items", str(job["work_item_id"]))
            completed = False
            if work_record is not None:
                work = parse_work_item(work_record.payload)
                completed = (
                    work.project_id == project_id
                    and work.status == "completed"
                    and projection_current
                )
            updates.append({
                "job_id": job["job_id"],
                "status": (
                    "completed"
                    if completed
                    else "blocked-awaiting-work-graph-update"
                ),
            })
        sanitized["projection_updates"] = updates
    state_digest = queue.state_digest()
    target = runtime_queue_path(store.data_root, project_id)
    target_ref = ".krcn/" + target.relative_to(store.data_root).as_posix()
    action_digest = _digest({"action": action, "arguments": sanitized, "state_digest": state_digest})
    mutation = plan_mutation(
        ownership, operation="update" if target.exists() else "create",
        target_ref=target_ref, expected_ownership="runtime",
        change_digest=action_digest, reversible=True,
    )
    plan_id = _digest({"action_digest": action_digest, "mutation": mutation.as_dict()})
    return queue, RuntimeQueuePlan(project_id, action, sanitized, state_digest, plan_id, mutation)


def apply_runtime_queue_action(
    queue: AgentRuntimeQueue,
    plan: RuntimeQueuePlan,
    authorization: MutationAuthorization,
) -> dict[str, object]:
    if authorization.plan.plan_id != plan.mutation.plan_id or not authorization.dry_run_verified:
        raise AgentRuntimeError("runtime queue authorization does not match")
    return queue.apply(plan.action, plan.arguments, plan.state_digest)

"""Durable exactly-once SQLite store for generalized effect contracts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping

from .effect_ledger import (
    EffectClaim,
    EffectReceipt,
    EffectReconciliation,
    parse_effect_claim,
    parse_effect_receipt,
    parse_effect_reconciliation,
)
from .validation_gate import ValidationGate


class EffectLedgerStoreError(ValueError):
    """Raised when a durable effect ledger operation conflicts or is unsafe."""


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS effect_claims (
  claim_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  project_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL,
  fencing_token INTEGER NOT NULL,
  claimed_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS effect_receipts (
  receipt_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL UNIQUE,
  outcome TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(claim_id) REFERENCES effect_claims(claim_id)
);
CREATE TABLE IF NOT EXISTS effect_reconciliations (
  reconciliation_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL UNIQUE,
  outcome TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(claim_id) REFERENCES effect_claims(claim_id)
);
CREATE INDEX IF NOT EXISTS idx_effect_claim_scope
  ON effect_claims(project_id, task_id, step_id);
"""


def _json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class EffectLedgerStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        if self.database_path.suffix != ".sqlite":
            raise EffectLedgerStoreError("effect ledger database must use .sqlite")
        for candidate in (self.database_path, *self.database_path.parents):
            if not candidate.exists():
                continue
            is_junction = getattr(candidate, "is_junction", lambda: False)()
            if candidate.is_symlink() or is_junction:
                raise EffectLedgerStoreError("effect ledger path may not use symlink or junction ancestors")
        if self.database_path.exists() and not self.database_path.is_file():
            raise EffectLedgerStoreError("effect ledger database path is invalid")
        parent = self.database_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    def record_claim(
        self,
        claim: EffectClaim | Mapping[str, object],
        *,
        validation_gate: ValidationGate | Mapping[str, object],
    ) -> dict[str, object]:
        checked = parse_effect_claim(
            claim.as_dict() if isinstance(claim, EffectClaim) else claim,
            validation_gate=validation_gate,
        )
        payload = checked.as_dict()
        encoded = _json(payload)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT claim_id,payload_json FROM effect_claims WHERE idempotency_key=?",
                (payload["effect"]["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                if existing["claim_id"] != checked.claim_id or existing["payload_json"] != encoded:
                    raise EffectLedgerStoreError("effect idempotency key already has a conflicting claim")
                return {"status": "current", "claim": payload, "execution_allowed": False}
            connection.execute(
                "INSERT INTO effect_claims(claim_id,idempotency_key,project_id,task_id,step_id,attempt_id,fencing_token,claimed_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    checked.claim_id, payload["effect"]["idempotency_key"],
                    payload["bindings"]["project_id"], payload["bindings"]["task_id"],
                    payload["bindings"]["step_id"], payload["bindings"]["attempt_id"],
                    payload["bindings"]["fencing_token"], payload["runtime"]["claimed_at"], encoded,
                ),
            )
            return {"status": "claimed", "claim": payload, "execution_allowed": True}

    def record_receipt(
        self,
        receipt: EffectReceipt | Mapping[str, object],
    ) -> dict[str, object]:
        candidate = receipt.as_dict() if isinstance(receipt, EffectReceipt) else receipt
        claim_id = candidate.get("claim_id") if isinstance(candidate, Mapping) else None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM effect_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            if row is None:
                raise EffectLedgerStoreError("effect receipt claim is not recorded")
            claim = parse_effect_claim(json.loads(row["payload_json"]))
            checked = parse_effect_receipt(candidate, claim=claim)
            payload = checked.as_dict()
            encoded = _json(payload)
            existing = connection.execute(
                "SELECT receipt_id,payload_json FROM effect_receipts WHERE claim_id=?", (claim.claim_id,)
            ).fetchone()
            if existing is not None:
                if existing["receipt_id"] != checked.receipt_id or existing["payload_json"] != encoded:
                    raise EffectLedgerStoreError("effect claim already has a conflicting terminal receipt")
                return {"status": "current", "receipt": payload, "effect_terminal": True}
            reconciled = connection.execute(
                "SELECT reconciliation_id FROM effect_reconciliations WHERE claim_id=?", (claim.claim_id,)
            ).fetchone()
            if reconciled is not None:
                raise EffectLedgerStoreError("reconciled claim may not receive a late receipt")
            connection.execute(
                "INSERT INTO effect_receipts(receipt_id,claim_id,outcome,finished_at,payload_json) VALUES(?,?,?,?,?)",
                (checked.receipt_id, claim.claim_id, payload["outcome"]["status"], payload["finished_at"], encoded),
            )
            return {"status": "recorded", "receipt": payload, "effect_terminal": True}

    def record_reconciliation(
        self,
        reconciliation: EffectReconciliation | Mapping[str, object],
    ) -> dict[str, object]:
        candidate = reconciliation.as_dict() if isinstance(reconciliation, EffectReconciliation) else reconciliation
        claim_id = candidate.get("claim_id") if isinstance(candidate, Mapping) else None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            claim_row = connection.execute(
                "SELECT payload_json FROM effect_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            if claim_row is None:
                raise EffectLedgerStoreError("reconciliation claim is not recorded")
            claim = parse_effect_claim(json.loads(claim_row["payload_json"]))
            receipt_row = connection.execute(
                "SELECT payload_json FROM effect_receipts WHERE claim_id=?", (claim.claim_id,)
            ).fetchone()
            receipt = None if receipt_row is None else parse_effect_receipt(json.loads(receipt_row["payload_json"]), claim=claim)
            checked = parse_effect_reconciliation(candidate, claim=claim, receipt=receipt)
            payload = checked.as_dict()
            encoded = _json(payload)
            existing = connection.execute(
                "SELECT reconciliation_id,payload_json FROM effect_reconciliations WHERE claim_id=?", (claim.claim_id,)
            ).fetchone()
            if existing is not None:
                if existing["reconciliation_id"] != payload["reconciliation_id"] or existing["payload_json"] != encoded:
                    raise EffectLedgerStoreError("effect claim already has a conflicting reconciliation")
                return {"status": "current", "reconciliation": payload}
            connection.execute(
                "INSERT INTO effect_reconciliations(reconciliation_id,claim_id,outcome,observed_at,payload_json) VALUES(?,?,?,?,?)",
                (payload["reconciliation_id"], claim.claim_id, payload["outcome"], payload["observed_at"], encoded),
            )
            return {"status": "recorded", "reconciliation": payload}

    def claim_status(self, claim_id: str) -> dict[str, object]:
        with self._connection() as connection:
            claim_row = connection.execute(
                "SELECT payload_json FROM effect_claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            if claim_row is None:
                return {"found": False, "claim_id": claim_id}
            claim = parse_effect_claim(json.loads(claim_row["payload_json"]))
            receipt_row = connection.execute(
                "SELECT payload_json FROM effect_receipts WHERE claim_id=?", (claim_id,)
            ).fetchone()
            reconciliation_row = connection.execute(
                "SELECT payload_json FROM effect_reconciliations WHERE claim_id=?", (claim_id,)
            ).fetchone()
            receipt = None if receipt_row is None else parse_effect_receipt(json.loads(receipt_row["payload_json"]), claim=claim)
            reconciliation = None if reconciliation_row is None else parse_effect_reconciliation(
                json.loads(reconciliation_row["payload_json"]), claim=claim, receipt=receipt
            )
            recovery_required = receipt is None and reconciliation is None
            return {
                "found": True, "claim_id": claim_id,
                "idempotency_key": claim.payload["effect"]["idempotency_key"],
                "receipt_id": None if receipt is None else receipt.receipt_id,
                "receipt_status": None if receipt is None else receipt.payload["outcome"]["status"],
                "reconciliation_id": None if reconciliation is None else reconciliation.payload["reconciliation_id"],
                "reconciliation_outcome": None if reconciliation is None else reconciliation.payload["outcome"],
                "recovery_required": recovery_required,
                "execution_allowed": False,
                "grants_authority": False,
            }

    def recovery_required_claims(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT c.claim_id FROM effect_claims c LEFT JOIN effect_receipts r ON r.claim_id=c.claim_id LEFT JOIN effect_reconciliations x ON x.claim_id=c.claim_id WHERE r.claim_id IS NULL AND x.claim_id IS NULL ORDER BY c.claim_id"
            ).fetchall()
            return tuple(str(row["claim_id"]) for row in rows)

    def integrity_check(self) -> bool:
        with self._connection() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
            return bool(row and row[0] == "ok" and not foreign)

"""Capability, policy, skill, secret, worker, and verifier-gated SQLite SELECT."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .adapter_gate import authorize_adapter_operation, parse_adapter_descriptor, prepare_adapter_operation
from .capability_registry import CapabilitySelection, load_capability_registry, select_capability_records
from .component_runtime import RuntimeComponentRegistry, RuntimeComponentSpec
from .database_policy import require_database_statement
from .foundation import load_json
from .information_records import canonical_json
from .integrations import IntegrationMetadata
from .policies import UserPolicy
from .secret_provider import LocalFileSecretProvider, SecretLease
from .source_bindings import SourceBinding


COMPONENT_IDS = {
    "skill": "database-query-skill-runtime",
    "adapter": "sqlite-read-only-adapter-runtime",
    "secret-provider": "local-secret-provider-runtime",
    "worker": "sqlite-select-worker-runtime",
    "verifier": "sqlite-result-verifier-runtime",
}
CAPABILITY_RECORD_REFS = (
    "database-query-skill",
    "local-secret-provider",
    "read-only-worker-agent",
    "sqlite-read-only-adapter",
    "verifier-agent",
)
REQUIRED_CAPABILITIES = (
    "database.query.validate",
    "database.select",
    "evidence.verify",
    "plan.execute",
    "secret.resolve",
)


class SqliteReferenceRuntimeError(ValueError):
    """Raised before data is returned when any reference-flow gate fails."""


def _safe_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest()}
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


@dataclass(frozen=True)
class SqliteSelectResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    result_digest: str
    adapter_request_id: str
    selection_digest: str
    matched_policy_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "sqlite-read-only",
            "column_names": list(self.columns),
            "row_count": len(self.rows),
            "result_digest": self.result_digest,
            "adapter_request_id": self.adapter_request_id,
            "selection_digest": self.selection_digest,
            "matched_policy_ids": list(self.matched_policy_ids),
            "matched_rule_ids": list(self.matched_rule_ids),
            "secret_reference_used": True,
            "secret_value_disclosed": False,
            "rows_disclosed": False,
            "mutation_effect": False,
            "network_effect": False,
        }


def _result_digest(columns: tuple[str, ...], rows: tuple[tuple[object, ...], ...]) -> str:
    normalized = {
        "columns": list(columns),
        "rows": [[_safe_value(value) for value in row] for row in rows],
    }
    return hashlib.sha256(canonical_json(normalized)).hexdigest()


def _execute_sqlite_uri(
    lease: SecretLease,
    statement: str,
    maximum_rows: int,
) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
    try:
        uri = lease.reveal().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SqliteReferenceRuntimeError("SQLite connection secret must be UTF-8") from exc
    if not uri.startswith("file:") or "mode=ro" not in uri:
        raise SqliteReferenceRuntimeError(
            "SQLite connection secret must declare read-only URI mode"
        )
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            connection.execute("PRAGMA query_only = ON")
            cursor = connection.execute(statement)
            columns = tuple(item[0] for item in (cursor.description or ()))
            rows = tuple(cursor.fetchmany(maximum_rows + 1))
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise SqliteReferenceRuntimeError("SQLite read-only query failed") from exc
    if len(rows) > maximum_rows:
        raise SqliteReferenceRuntimeError("SQLite result exceeds the declared row limit")
    return columns, rows


class SqliteReferenceRuntime:
    """One explicitly registered local reference runtime; no host discovery."""

    def __init__(self, repo_root: Path, secret_root: Path) -> None:
        self._repo_root = repo_root.resolve()
        self._capabilities = load_capability_registry(self._repo_root)
        self._components = RuntimeComponentRegistry(self._capabilities)
        self._secret_provider = LocalFileSecretProvider(secret_root)
        self._adapter = parse_adapter_descriptor(
            load_json(
                self._repo_root
                / ".ai"
                / "registry"
                / "adapters"
                / "sqlite-read-only.json"
            )
        )
        self._register_components()
        self._selection = select_capability_records(
            self._capabilities,
            CAPABILITY_RECORD_REFS,
            REQUIRED_CAPABILITIES,
        )
        if self._selection.approval_triggers:
            raise SqliteReferenceRuntimeError(
                "read-only reference selection unexpectedly requires mutation approval"
            )

    def _register_components(self) -> None:
        registrations = (
            RuntimeComponentSpec(
                COMPONENT_IDS["skill"],
                "skill",
                ("database-query-skill",),
                ("database.query.validate",),
                (),
                require_database_statement,
            ),
            RuntimeComponentSpec(
                COMPONENT_IDS["adapter"],
                "adapter",
                ("sqlite-read-only-adapter",),
                ("database.select",),
                ("execute", "read"),
                _execute_sqlite_uri,
            ),
            RuntimeComponentSpec(
                COMPONENT_IDS["secret-provider"],
                "secret-provider",
                ("local-secret-provider",),
                ("secret.resolve",),
                ("read",),
                self._secret_provider.resolve,
            ),
            RuntimeComponentSpec(
                COMPONENT_IDS["worker"],
                "worker",
                ("read-only-worker-agent",),
                ("plan.execute",),
                ("execute", "read"),
                lambda operation: operation(),
            ),
            RuntimeComponentSpec(
                COMPONENT_IDS["verifier"],
                "verifier",
                ("verifier-agent",),
                ("evidence.verify",),
                ("execute", "read"),
                lambda columns, rows, digest: _result_digest(columns, rows) == digest,
            ),
        )
        for registration in registrations:
            self._components.register(registration)

    @property
    def selection(self) -> CapabilitySelection:
        return self._selection

    def component_catalog(self) -> tuple[dict[str, object], ...]:
        return self._components.public_catalog()

    def execute_select(
        self,
        integration: IntegrationMetadata,
        binding: SourceBinding,
        statement: str,
        policies: Sequence[UserPolicy],
        *,
        maximum_rows: int = 1_000,
    ) -> SqliteSelectResult:
        if not 1 <= maximum_rows <= 10_000:
            raise SqliteReferenceRuntimeError("SQLite row limit is invalid")
        if (
            integration.status != "active"
            or integration.adapter_id != self._adapter.adapter_id
            or integration.source_binding_ref != binding.binding_id
            or binding.source_kind != "database"
            or binding.source_id != integration.integration_id
            or binding.locator.kind != "connection-ref"
            or binding.default_access != "read-only"
            or set(integration.policy_refs) != set(binding.policy_refs)
        ):
            raise SqliteReferenceRuntimeError(
                "SQLite integration and source binding do not match"
            )
        connection_name = binding.locator.value
        reference = integration.secret_refs.get(connection_name)
        if reference is None:
            raise SqliteReferenceRuntimeError(
                "SQLite binding does not identify an available secret reference"
            )
        policy_by_id = {policy.policy_id: policy for policy in policies}
        if set(integration.policy_refs) - set(policy_by_id):
            raise SqliteReferenceRuntimeError(
                "SQLite integration references unavailable policies"
            )
        selected_policies = tuple(policy_by_id[item] for item in integration.policy_refs)
        skill = self._components.require(COMPONENT_IDS["skill"], "skill")
        skill.spec.callback(
            statement,
            selected_policies,
            integration_id=integration.integration_id,
        )
        adapter_request = prepare_adapter_operation(
            self._adapter,
            binding,
            "select",
            selected_policies,
        )
        authorize_adapter_operation(adapter_request)
        secret_provider = self._components.require(
            COMPONENT_IDS["secret-provider"], "secret-provider"
        )
        lease = secret_provider.spec.callback(reference)
        if not isinstance(lease, SecretLease):
            raise SqliteReferenceRuntimeError("secret provider result is invalid")
        adapter = self._components.require(COMPONENT_IDS["adapter"], "adapter")
        worker = self._components.require(COMPONENT_IDS["worker"], "worker")

        def operation():
            return adapter.spec.callback(lease, statement, maximum_rows)

        executed = worker.spec.callback(operation)
        if (
            not isinstance(executed, tuple)
            or len(executed) != 2
            or not isinstance(executed[0], tuple)
            or not isinstance(executed[1], tuple)
        ):
            raise SqliteReferenceRuntimeError("SQLite adapter result is invalid")
        columns, rows = executed
        digest = _result_digest(columns, rows)
        verifier = self._components.require(COMPONENT_IDS["verifier"], "verifier")
        if verifier.spec.callback(columns, rows, digest) is not True:
            raise SqliteReferenceRuntimeError("SQLite result verification failed")
        return SqliteSelectResult(
            columns,
            rows,
            digest,
            adapter_request.request_id,
            self._selection.selection_digest,
            adapter_request.matched_policy_ids,
            adapter_request.matched_rule_ids,
        )

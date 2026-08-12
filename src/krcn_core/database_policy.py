"""Fail-closed database statement classification and policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .policies import PolicyDecision, UserPolicy, evaluate_policies


DDL_KEYWORDS = {
    "ALTER",
    "COMMENT",
    "CREATE",
    "DROP",
    "GRANT",
    "RENAME",
    "REVOKE",
    "TRUNCATE",
}
DML_KEYWORDS = {
    "DELETE": "delete",
    "INSERT": "insert",
    "MERGE": "merge",
    "UPDATE": "update",
}
EXECUTE_KEYWORDS = {"BEGIN", "CALL", "DECLARE", "DO", "EXEC", "EXECUTE"}
SESSION_KEYWORDS = {"RESET", "SET", "SHOW", "USE"}
TRANSACTION_KEYWORDS = {"COMMIT", "RELEASE", "ROLLBACK", "SAVEPOINT", "START"}


class DatabaseStatementError(ValueError):
    """Raised when a database statement is malformed or not authorized."""


@dataclass(frozen=True)
class DatabaseStatementAuthorization:
    classification: str
    decision: PolicyDecision

    @property
    def permitted(self) -> bool:
        return self.classification == "select" and self.decision.permitted


@dataclass(frozen=True)
class OracleMetadataTemplate:
    template_id: str
    statement: str
    bind_names: tuple[str, ...]
    collection_mode: str


@dataclass(frozen=True)
class OracleMetadataAuthorization:
    template: OracleMetadataTemplate
    statement_decision: PolicyDecision
    metadata_decision: PolicyDecision | None
    session_approved: bool

    @property
    def permitted(self) -> bool:
        if not self.statement_decision.permitted:
            return False
        if self.template.collection_mode == "select-compatible":
            return True
        return bool(
            self.session_approved
            and self.metadata_decision is not None
            and self.metadata_decision.permitted
        )


ORACLE_METADATA_TEMPLATES: Mapping[str, OracleMetadataTemplate] = {
    "inventory-objects": OracleMetadataTemplate(
        "inventory-objects",
        "SELECT OWNER, OBJECT_NAME, OBJECT_TYPE, SUBOBJECT_NAME, OBJECT_ID, STATUS, LAST_DDL_TIME, TIMESTAMP, GENERATED, EDITION_NAME FROM ALL_OBJECTS WHERE OWNER = :owner",
        ("owner",),
        "select-compatible",
    ),
    "fetch-ddl": OracleMetadataTemplate(
        "fetch-ddl",
        "SELECT DBMS_METADATA.GET_DDL(:object_type, :object_name, :owner) FROM DUAL",
        ("object_type", "object_name", "owner"),
        "select-compatible",
    ),
    "fetch-dependent-ddl": OracleMetadataTemplate(
        "fetch-dependent-ddl",
        "SELECT DBMS_METADATA.GET_DEPENDENT_DDL(:object_type, :base_object_name, :owner) FROM DUAL",
        ("object_type", "base_object_name", "owner"),
        "select-compatible",
    ),
    "fetch-granted-ddl": OracleMetadataTemplate(
        "fetch-granted-ddl",
        "SELECT DBMS_METADATA.GET_GRANTED_DDL(:object_type, :grantee) FROM DUAL",
        ("object_type", "grantee"),
        "select-compatible",
    ),
    "batch-open": OracleMetadataTemplate(
        "batch-open",
        "BEGIN DBMS_METADATA.OPEN(:object_type)",
        ("object_type",),
        "batch-open",
    ),
}


def _lex_sql(statement: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        next_char = statement[index + 1] if index + 1 < length else ""
        if char.isspace():
            index += 1
            continue
        if char == "-" and next_char == "-":
            index += 2
            while index < length and statement[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            end = statement.find("*/", index + 2)
            if end < 0:
                raise DatabaseStatementError("unterminated SQL comment")
            index = end + 2
            continue
        if char == "'":
            index += 1
            while index < length:
                if statement[index] == "'":
                    if index + 1 < length and statement[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise DatabaseStatementError("unterminated SQL string")
            tokens.append("<LITERAL>")
            continue
        if char == '"':
            index += 1
            while index < length:
                if statement[index] == '"':
                    if index + 1 < length and statement[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise DatabaseStatementError("unterminated quoted identifier")
            tokens.append("<IDENTIFIER>")
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (statement[end].isalnum() or statement[end] in "_$#"):
                end += 1
            tokens.append(statement[index:end].upper())
            index = end
            continue
        if char in "();,":
            tokens.append(char)
        index += 1
    return tokens


def _single_statement_tokens(statement: str) -> list[str]:
    tokens = _lex_sql(statement)
    semicolons = [index for index, token in enumerate(tokens) if token == ";"]
    if not semicolons:
        return tokens
    if len(semicolons) > 1 or semicolons[0] != len(tokens) - 1:
        return ["<MULTIPLE>"]
    return tokens[:-1]


def _top_level_operation(tokens: list[str], start: int) -> tuple[str, int] | None:
    depth = 0
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token == "(":
            depth += 1
            continue
        if token == ")":
            depth = max(0, depth - 1)
            continue
        if depth == 0 and token in {"SELECT", *DML_KEYWORDS}:
            return token, index
    return None


def _classify_select(tokens: list[str], start: int) -> str:
    depth = 0
    for index in range(start + 1, len(tokens)):
        token = tokens[index]
        if token == "(":
            depth += 1
            continue
        if token == ")":
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        if token == "INTO":
            return "select-into"
        if token == "FOR" and index + 1 < len(tokens) and tokens[index + 1] == "UPDATE":
            return "select-for-update"
    return "select"


def classify_database_statement(statement: str) -> str:
    """Classify one SQL statement without connecting to a database."""

    if not isinstance(statement, str) or not statement.strip():
        return "empty"
    tokens = _single_statement_tokens(statement)
    if tokens == ["<MULTIPLE>"]:
        return "multiple"
    if not tokens:
        return "empty"
    keyword = tokens[0]
    operation_index = 0
    if keyword == "WITH":
        operation = _top_level_operation(tokens, 1)
        if operation is None:
            return "unknown"
        keyword, operation_index = operation
    if keyword == "SELECT":
        return _classify_select(tokens, operation_index)
    if keyword in DML_KEYWORDS:
        return DML_KEYWORDS[keyword]
    if keyword == "ALTER" and len(tokens) > 1 and tokens[1] in {"SESSION", "SYSTEM"}:
        return "session"
    if keyword in DDL_KEYWORDS:
        return "ddl"
    if keyword in EXECUTE_KEYWORDS:
        return "execute"
    if keyword in SESSION_KEYWORDS:
        return "session"
    if keyword in TRANSACTION_KEYWORDS:
        return "transaction"
    return "unknown"


def authorize_database_statement(
    statement: str,
    policies: Sequence[UserPolicy],
    *,
    integration_id: str,
) -> DatabaseStatementAuthorization:
    """Evaluate a classified statement against preserved integration policies."""

    classification = classify_database_statement(statement)
    decision = evaluate_policies(
        policies,
        resource_type="database",
        operation=classification,
        scope_refs={"integration": integration_id},
    )
    return DatabaseStatementAuthorization(classification, decision)


def require_database_statement(
    statement: str,
    policies: Sequence[UserPolicy],
    *,
    integration_id: str,
) -> DatabaseStatementAuthorization:
    """Return authorization or fail before a database adapter can execute."""

    authorization = authorize_database_statement(
        statement,
        policies,
        integration_id=integration_id,
    )
    if not authorization.permitted:
        raise DatabaseStatementError(
            "database statement is not permitted by the effective user policy"
        )
    return authorization


def require_oracle_metadata_template(
    template_id: str,
    bind_values: Mapping[str, object],
    policies: Sequence[UserPolicy],
    *,
    integration_id: str,
    session_approved: bool = False,
) -> OracleMetadataAuthorization:
    """Authorize one fixed Oracle metadata template without accepting free SQL."""

    template = ORACLE_METADATA_TEMPLATES.get(template_id)
    if template is None:
        raise DatabaseStatementError("Oracle metadata template is not registered")
    if set(bind_values) != set(template.bind_names):
        raise DatabaseStatementError("Oracle metadata bind values do not match")
    if any(
        not isinstance(value, str) or not value.strip() or "\x00" in value
        for value in bind_values.values()
    ):
        raise DatabaseStatementError("Oracle metadata bind value is invalid")
    if template.collection_mode == "select-compatible":
        statement = require_database_statement(
            template.statement,
            policies,
            integration_id=integration_id,
        )
        return OracleMetadataAuthorization(
            template,
            statement.decision,
            None,
            bool(session_approved),
        )
    statement_decision = evaluate_policies(
        policies,
        resource_type="database",
        operation="execute",
        scope_refs={"integration": integration_id},
    )
    metadata_decision = evaluate_policies(
        policies,
        resource_type="database-metadata",
        operation="batch-open",
        scope_refs={"integration": integration_id},
    )
    authorization = OracleMetadataAuthorization(
        template,
        statement_decision,
        metadata_decision,
        bool(session_approved),
    )
    if not authorization.permitted:
        raise DatabaseStatementError(
            "Oracle batch metadata requires execute, metadata, and session approval"
        )
    return authorization

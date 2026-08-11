"""Fail-closed database statement classification and policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

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

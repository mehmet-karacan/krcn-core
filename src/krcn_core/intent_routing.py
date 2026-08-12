"""Validated client-neutral natural-language routing contracts."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*$")
CLIENTS = {"cli", "sdk", "mcp", "plugin", "codex", "claude", "generic-ai"}


class IntentRoutingError(ValueError):
    """Raised when the canonical intent routing contract is invalid."""


@dataclass(frozen=True)
class IntentRoute:
    route_id: str
    action: str
    application_operation: str
    terms: tuple[str, ...]
    directory_only: bool
    required_inputs: tuple[str, ...]
    inferred_fields: tuple[str, ...]
    source_access: str
    copy_source: bool
    exact_plan_required: bool
    user_data_approval_required: bool
    client_specific: bool
    supported_clients: tuple[str, ...]


def load_intent_routes(repo_root: Path) -> tuple[IntentRoute, ...]:
    """Load the shared route table used by every action-capable client."""

    path = repo_root / "config" / "intent-routing.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntentRoutingError("intent routing configuration is unreadable") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_ref",
        "schema_version",
        "routes",
    }:
        raise IntentRoutingError("intent routing configuration fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/intent-routing.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise IntentRoutingError("intent routing schema identity is invalid")
    records = payload.get("routes")
    if not isinstance(records, list) or not records:
        raise IntentRoutingError("intent routing must contain routes")
    routes: list[IntentRoute] = []
    route_ids: set[str] = set()
    for record in records:
        expected = {
            "route_id",
            "action",
            "application_operation",
            "terms",
            "directory_only",
            "required_inputs",
            "inferred_fields",
            "source_access",
            "copy_source",
            "exact_plan_required",
            "user_data_approval_required",
            "client_specific",
            "supported_clients",
        }
        if not isinstance(record, dict) or set(record) != expected:
            raise IntentRoutingError("intent route fields are invalid")
        route_id = record.get("route_id")
        action = record.get("action")
        operation = record.get("application_operation")
        if (
            not isinstance(route_id, str)
            or not IDENTIFIER.fullmatch(route_id)
            or route_id in route_ids
            or not isinstance(action, str)
            or not IDENTIFIER.fullmatch(action)
            or not isinstance(operation, str)
            or not IDENTIFIER.fullmatch(operation)
        ):
            raise IntentRoutingError("intent route identity is invalid")
        route_ids.add(route_id)
        terms = record.get("terms")
        required_inputs = record.get("required_inputs")
        inferred_fields = record.get("inferred_fields")
        supported_clients = record.get("supported_clients")
        if (
            not isinstance(terms, list)
            or not terms
            or any(not isinstance(item, str) or not item.strip() for item in terms)
            or len(set(terms)) != len(terms)
            or required_inputs != ["local-directory"]
            or inferred_fields != ["project-name", "project-id", "workspace-id", "binding-id"]
            or not isinstance(supported_clients, list)
            or set(supported_clients) != CLIENTS
            or len(supported_clients) != len(CLIENTS)
        ):
            raise IntentRoutingError("intent route inputs or clients are invalid")
        if (
            record.get("source_access") != "read-only"
            or record.get("copy_source") is not False
            or record.get("directory_only") is not True
            or record.get("exact_plan_required") is not True
            or record.get("user_data_approval_required") is not True
            or record.get("client_specific") is not False
        ):
            raise IntentRoutingError("intent route safety boundary is invalid")
        routes.append(
            IntentRoute(
                route_id=route_id,
                action=action,
                application_operation=operation,
                terms=tuple(terms),
                directory_only=True,
                required_inputs=tuple(required_inputs),
                inferred_fields=tuple(inferred_fields),
                source_access="read-only",
                copy_source=False,
                exact_plan_required=True,
                user_data_approval_required=True,
                client_specific=False,
                supported_clients=tuple(supported_clients),
            )
        )
    return tuple(routes)


def project_learning_route(repo_root: Path) -> IntentRoute:
    for route in load_intent_routes(repo_root):
        if route.route_id == "project-learning":
            return route
    raise IntentRoutingError("project-learning route is missing")


def project_integration_route(repo_root: Path) -> IntentRoute:
    for route in load_intent_routes(repo_root):
        if route.route_id == "project-integration":
            return route
    raise IntentRoutingError("project-integration route is missing")


def route_project_request(repo_root: Path, request_text: str) -> IntentRoute:
    """Prefer complete integration when one request contains both route vocabularies."""

    if not isinstance(request_text, str):
        raise IntentRoutingError("project request must be text")
    def words_for(value: str) -> set[str]:
        folded = unicodedata.normalize("NFKD", value.casefold())
        normalized = "".join(
            character for character in folded if not unicodedata.combining(character)
        ).translate(str.maketrans({"ı": "i", "ş": "s"}))
        return set(re.findall(r"[a-z]+", normalized))

    words = words_for(request_text)
    routes = load_intent_routes(repo_root)
    matches = [
        route
        for route in routes
        if words.intersection(word for term in route.terms for word in words_for(term))
    ]
    integration = next(
        (route for route in matches if route.route_id == "project-integration"),
        None,
    )
    if integration is not None:
        return integration
    if matches:
        return matches[0]
    raise IntentRoutingError("project request route was not recognized")

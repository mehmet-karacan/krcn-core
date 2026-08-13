"""Natural-language project listing and read-only menu selection."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .json_documents import canonical_json_bytes


LIST_REQUESTS = {
    "projeler",
    "projelerim",
    "proje listesi",
    "projeleri listele",
    "entegre projeler",
    "hangi projeler entegre",
    "hangi projeler bize entegre",
    "hangi projeler sisteme entegre",
}
PROJECT_ACTION = re.compile(
    r"^\s*(?P<project>.+?)\s+projes(?:ini|ine)\s+"
    r"(?:kontrol\s+et|göster|aç|gir|bak|incele)\s*[.!]?\s*$",
    re.IGNORECASE,
)
ORDINAL = re.compile(r"^\s*(?P<position>[1-9][0-9]*)\s*[.]?\s*$")


class ProjectNavigationError(ValueError):
    """Raised when a request is not a project navigation command."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class ProjectNavigationIntent:
    operation: str
    project_ref: str | None
    intent_digest: str

    def service_arguments(self, working_directory: str) -> dict[str, object]:
        if self.operation == "project.list":
            return {}
        return {
            "working_directory": working_directory,
            "project_ref": self.project_ref,
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "project_ref": self.project_ref,
            "read_only": True,
            "selection_grants_authority": False,
            "intent_digest": self.intent_digest,
        }


def parse_project_navigation_intent(text: str) -> ProjectNavigationIntent:
    """Recognize a project list, position, or explicit inspection request."""

    if not isinstance(text, str) or not text.strip():
        raise ProjectNavigationError("project navigation request is required")
    normalized = re.sub(r"\s+", " ", text.casefold().strip(" .!?"))
    if normalized in LIST_REQUESTS:
        identity = {"operation": "project.list", "project_ref": None}
        return ProjectNavigationIntent("project.list", None, _digest(identity))
    ordinal = ORDINAL.fullmatch(text)
    if ordinal is not None:
        project_ref = ordinal.group("position")
    else:
        action = PROJECT_ACTION.fullmatch(text)
        if action is None:
            raise ProjectNavigationError(
                "request is not a project navigation command"
            )
        project_ref = action.group("project").strip()
    identity = {"operation": "project.resume", "project_ref": project_ref}
    return ProjectNavigationIntent(
        "project.resume", project_ref, _digest(identity),
    )

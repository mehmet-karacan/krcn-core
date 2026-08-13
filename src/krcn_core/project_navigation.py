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
WORK_LIST = re.compile(
    r"^\s*(?:(?P<project>.+?)\s+)?"
    r"(?:(?P<lifecycle>aktif|geçmiş|arsiv|arşiv)\s+)?"
    r"(?P<kind>görev(?:ler|leri)?|talep(?:ler|leri)?|"
    r"defect(?:ler|leri)?|hata(?:lar|ları)?)"
    r"(?:\s+(?:listesi|listele|göster))?\s*[.!]?\s*$",
    re.IGNORECASE,
)

WORK_TYPES = {
    "görev": "task",
    "görevler": "task",
    "görevleri": "task",
    "talep": "request",
    "talepler": "request",
    "talepleri": "request",
    "defect": "defect",
    "defectler": "defect",
    "defectleri": "defect",
    "hata": "defect",
    "hatalar": "defect",
    "hataları": "defect",
}


class ProjectNavigationError(ValueError):
    """Raised when a request is not a project navigation command."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class ProjectNavigationIntent:
    operation: str
    project_ref: str | None
    intent_digest: str
    work_type: str | None = None
    lifecycle: str = "all"

    def service_arguments(self, working_directory: str) -> dict[str, object]:
        if self.operation == "project.list":
            return {}
        arguments: dict[str, object] = {
            "working_directory": working_directory,
        }
        if self.project_ref is not None:
            arguments["project_ref"] = self.project_ref
        if self.operation == "work.list":
            arguments.update({
                "work_type": self.work_type,
                "lifecycle": self.lifecycle,
                "limit": 100,
            })
        return arguments

    def public_summary(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "project_ref": self.project_ref,
            "work_type": self.work_type,
            "lifecycle": self.lifecycle,
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
    work_list = WORK_LIST.fullmatch(text)
    if work_list is not None:
        project_ref = work_list.group("project")
        project_ref = project_ref.strip() if project_ref else None
        kind = work_list.group("kind").casefold()
        lifecycle_text = work_list.group("lifecycle")
        lifecycle = "all"
        if lifecycle_text is not None:
            lifecycle = (
                "active" if lifecycle_text.casefold() == "aktif"
                else "historical"
            )
        work_type = WORK_TYPES[kind]
        identity = {
            "operation": "work.list",
            "project_ref": project_ref,
            "work_type": work_type,
            "lifecycle": lifecycle,
        }
        return ProjectNavigationIntent(
            "work.list",
            project_ref,
            _digest(identity),
            work_type=work_type,
            lifecycle=lifecycle,
        )
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

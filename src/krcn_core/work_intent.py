"""Client-neutral natural-language routing for explicit project work items."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
EXTERNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CREATE_PATTERNS = (
    re.compile(
        r"^\s*(?P<external>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\s+"
        r"(?P<kind>talebini|talebi|defectini|defecti|görevini|görevi)\s+"
        r"(?P<project>[a-z][a-z0-9-]*)\s+için\s+"
        r"(?P<action>oluştur|aç|kaydet)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?P<project>[a-z][a-z0-9-]*)\s+için\s+"
        r"(?P<external>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\s+"
        r"(?P<kind>talebini|talebi|defectini|defecti|görevini|görevi)\s+"
        r"(?P<action>oluştur|aç|kaydet)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
)
WORK_TYPE_BY_TERM = {
    "talebini": "request",
    "talebi": "request",
    "defectini": "defect",
    "defecti": "defect",
    "görevini": "task",
    "görevi": "task",
}
TITLE_BY_TYPE = {
    "request": "Talep",
    "defect": "Defect",
    "task": "Görev",
}


class WorkIntentError(ValueError):
    """Raised when a natural-language work request is absent or ambiguous."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _portable_external_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug or not IDENTIFIER.fullmatch("x-" + slug):
        raise WorkIntentError("work external identity is not portable")
    return slug


@dataclass(frozen=True)
class WorkCreateIntent:
    project_id: str
    work_type: str
    external_id: str
    work_item_id: str
    status: str
    intent_digest: str

    def service_arguments(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "work_type": self.work_type,
            "title": f"{TITLE_BY_TYPE[self.work_type]} {self.external_id}",
            "description": "",
            "status": self.status,
            "acceptance_criteria": [],
            "relations": [],
            "evidence": [],
            "provenance": {
                "source_kind": "user",
                "source_ref": f"natural-language:{self.external_id}",
            },
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "operation": "work.item.put",
            "project_id": self.project_id,
            "work_type": self.work_type,
            "external_id": self.external_id,
            "work_item_id": self.work_item_id,
            "default_status": self.status,
            "exact_plan_required": True,
            "user_data_approval_required": True,
            "intent_digest": self.intent_digest,
        }


def parse_work_create_intent(request_text: str) -> WorkCreateIntent:
    """Parse one explicit create request without guessing project or work type."""

    if not isinstance(request_text, str) or not request_text.strip():
        raise WorkIntentError("work request text is required")
    match = next((pattern.fullmatch(request_text) for pattern in CREATE_PATTERNS if pattern.fullmatch(request_text)), None)
    if match is None:
        raise WorkIntentError("request is not an explicit project work-item creation")
    project_id = match.group("project").casefold()
    external_id = match.group("external")
    kind = match.group("kind").casefold()
    if not IDENTIFIER.fullmatch(project_id):
        raise WorkIntentError("work project identity is invalid")
    if not EXTERNAL_ID.fullmatch(external_id):
        raise WorkIntentError("work external identity is invalid")
    work_type = WORK_TYPE_BY_TERM[kind]
    work_item_id = f"{project_id}-{work_type}-{_portable_external_slug(external_id)}"
    identity = {
        "operation": "work.item.put",
        "project_id": project_id,
        "work_type": work_type,
        "external_id": external_id,
        "work_item_id": work_item_id,
        "status": "proposed",
    }
    return WorkCreateIntent(
        project_id,
        work_type,
        external_id,
        work_item_id,
        "proposed",
        _digest(identity),
    )

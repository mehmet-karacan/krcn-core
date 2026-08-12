"""Validated durable state for complete project integration lifecycles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SCAN_MODES = {"manual", "automatic"}
SCAN_REASONS = {
    "explicit-integration-request",
    "explicit-rescan-request",
    "freshness-expired",
    "missing-integration-stage",
    "source-state-missing",
}
STAGE_IDS = (
    "registration",
    "discovery",
    "knowledge",
    "capability-profile",
    "vector-index",
    "verification",
)


class ProjectIntegrationStateError(ValueError):
    """Raised when a project integration state is incomplete or unsafe."""


@dataclass(frozen=True)
class ProjectIntegrationState:
    project_id: str
    scan_sequence: int
    scan_mode: str
    scan_reason: str
    freshness_hours: int
    source_digest: str
    knowledge_digest: str
    embedding_profile_id: str
    role_refs: tuple[str, ...]
    skill_refs: tuple[str, ...]
    stages: Mapping[str, str]

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-integration-state.schema.json",
            "schema_version": 1,
            "project_id": self.project_id,
            "scan_sequence": self.scan_sequence,
            "scan_mode": self.scan_mode,
            "scan_reason": self.scan_reason,
            "freshness_hours": self.freshness_hours,
            "source_digest": self.source_digest,
            "knowledge_digest": self.knowledge_digest,
            "embedding_profile_id": self.embedding_profile_id,
            "role_refs": list(self.role_refs),
            "skill_refs": list(self.skill_refs),
            "stages": dict(self.stages),
        }


def _identifier_list(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ProjectIntegrationStateError(f"{label} must be a unique identifier list")
    return tuple(value)


def parse_project_integration_state(payload: object) -> ProjectIntegrationState:
    """Parse a complete integration state without accepting partial success."""

    expected = {
        "schema_ref",
        "schema_version",
        "project_id",
        "scan_sequence",
        "scan_mode",
        "scan_reason",
        "freshness_hours",
        "source_digest",
        "knowledge_digest",
        "embedding_profile_id",
        "role_refs",
        "skill_refs",
        "stages",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ProjectIntegrationStateError("project integration state fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/project-integration-state.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise ProjectIntegrationStateError("project integration state schema is invalid")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id):
        raise ProjectIntegrationStateError("project integration project_id is invalid")
    scan_sequence = payload.get("scan_sequence")
    freshness_hours = payload.get("freshness_hours")
    if (
        not isinstance(scan_sequence, int)
        or isinstance(scan_sequence, bool)
        or scan_sequence < 1
        or not isinstance(freshness_hours, int)
        or isinstance(freshness_hours, bool)
        or not 1 <= freshness_hours <= 8760
    ):
        raise ProjectIntegrationStateError("project integration scan values are invalid")
    scan_mode = payload.get("scan_mode")
    scan_reason = payload.get("scan_reason")
    if scan_mode not in SCAN_MODES or scan_reason not in SCAN_REASONS:
        raise ProjectIntegrationStateError("project integration scan identity is invalid")
    source_digest = payload.get("source_digest")
    knowledge_digest = payload.get("knowledge_digest")
    if (
        not isinstance(source_digest, str)
        or not SHA256.fullmatch(source_digest)
        or not isinstance(knowledge_digest, str)
        or not SHA256.fullmatch(knowledge_digest)
    ):
        raise ProjectIntegrationStateError("project integration digests are invalid")
    embedding_profile_id = payload.get("embedding_profile_id")
    if (
        not isinstance(embedding_profile_id, str)
        or not IDENTIFIER.fullmatch(embedding_profile_id)
    ):
        raise ProjectIntegrationStateError("embedding profile id is invalid")
    stages = payload.get("stages")
    if (
        not isinstance(stages, dict)
        or set(stages) != set(STAGE_IDS)
        or any(value != "complete" for value in stages.values())
    ):
        raise ProjectIntegrationStateError("every project integration stage must be complete")
    return ProjectIntegrationState(
        project_id=project_id,
        scan_sequence=scan_sequence,
        scan_mode=str(scan_mode),
        scan_reason=str(scan_reason),
        freshness_hours=freshness_hours,
        source_digest=source_digest,
        knowledge_digest=knowledge_digest,
        embedding_profile_id=embedding_profile_id,
        role_refs=_identifier_list(payload.get("role_refs"), "role_refs"),
        skill_refs=_identifier_list(payload.get("skill_refs"), "skill_refs"),
        stages=dict(stages),
    )

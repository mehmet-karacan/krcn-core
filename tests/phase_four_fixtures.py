"""Synthetic Phase 4 records shared by hermetic tests."""

from __future__ import annotations

from krcn_core.information_records import parse_information_record, payload_digest
from krcn_core.source_bindings import parse_source_binding


def source_binding(*, revision: int = 1, source_id: str = "sample-project"):
    return parse_source_binding(
        {
            "schema_version": 1,
            "binding_id": "sample-project-local",
            "source_id": source_id,
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": "synthetic-fixture"},
            "default_access": "read-only",
            "capabilities": ["read", "metadata", "search"],
            "policy_refs": ["project-read-only"],
            "revision": revision,
        }
    )


def source_record(
    *,
    record_id: str = "sample-project-source",
    record_revision: int = 1,
    source_revision: str = "rev-1",
    source_digest: str = "a" * 64,
):
    content = {
        "title": "Sample project source",
        "source_id": "sample-project",
        "binding_id": "sample-project-local",
        "binding_revision": 1,
        "source_revision_id": source_revision,
        "source_digest": source_digest,
        "aliases": ["sample"],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": record_id,
            "information_class": "authoritative-source",
            "ownership": "user-data",
            "subject_ref": "source:sample-project",
            "revision": record_revision,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "system-observation",
                "evidence": [
                    {
                        "source_ref": "source:sample-project",
                        "revision_id": source_revision,
                        "digest": source_digest,
                        "relation": "observed-at",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


def knowledge_record(
    *,
    source_revision: str = "rev-1",
    source_digest: str = "a" * 64,
):
    content = {
        "title": "Database access rule",
        "text": "Only read operations are permitted",
        "keywords": ["database", "read-only"],
        "aliases": ["database rule"],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": "database-read-rule",
            "information_class": "knowledge",
            "ownership": "user-data",
            "subject_ref": "project:sample-project/database",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "source-derived",
                "evidence": [
                    {
                        "source_ref": "source:sample-project",
                        "revision_id": source_revision,
                        "digest": source_digest,
                        "relation": "supports",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )

#!/usr/bin/env python3
"""Measure local hybrid index build and query latency on synthetic catalogs."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.hybrid_retrieval import (  # noqa: E402
    HybridQuery,
    apply_hybrid_index,
    prepare_hybrid_index,
    retrieve_hybrid,
)
from krcn_core.information_records import parse_information_record, payload_digest  # noqa: E402
from krcn_core.knowledge_catalog import build_information_catalog  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.source_bindings import parse_source_binding  # noqa: E402


def _binding():
    return parse_source_binding(
        {
            "schema_version": 1,
            "binding_id": "benchmark-project-local",
            "source_id": "benchmark-project",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": "synthetic-benchmark"},
            "default_access": "read-only",
            "capabilities": ["read", "metadata", "search"],
            "policy_refs": [],
            "revision": 1,
        }
    )


def _source_record():
    content = {
        "title": "Synthetic benchmark source",
        "source_id": "benchmark-project",
        "binding_id": "benchmark-project-local",
        "binding_revision": 1,
        "source_revision_id": "rev-1",
        "source_digest": "b" * 64,
        "aliases": [],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": "benchmark-source",
            "information_class": "authoritative-source",
            "ownership": "user-data",
            "subject_ref": "source:benchmark-project",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "system-observation",
                "evidence": [
                    {
                        "source_ref": "source:benchmark-project",
                        "revision_id": "rev-1",
                        "digest": "b" * 64,
                        "relation": "observed-at",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


def _knowledge(index: int):
    topic = ("database", "deployment", "architecture", "testing")[index % 4]
    record_id = f"benchmark-record-{index:05d}"
    content = {
        "title": f"{topic.title()} reference {index}",
        "text": f"Synthetic {topic} guidance for deterministic retrieval case {index}",
        "keywords": [topic, f"case-{index}"],
        "aliases": [],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": record_id,
            "information_class": "knowledge",
            "ownership": "user-data",
            "subject_ref": f"project:benchmark-project/{record_id}",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "source-derived",
                "evidence": [
                    {
                        "source_ref": "source:benchmark-project",
                        "revision_id": "rev-1",
                        "digest": "b" * 64,
                        "relation": "supports",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


def measure(size: int, query_count: int) -> dict[str, object]:
    catalog = build_information_catalog(
        [_binding()],
        [_source_record(), *(_knowledge(index) for index in range(size))],
    )
    ownership = OwnershipResolver.from_repository(REPO_ROOT)
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory) / ".krcn"
        plan = prepare_hybrid_index(home, catalog, ownership)
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.plan_id, True),
        )
        started = time.perf_counter()
        apply_hybrid_index(home, catalog, plan, authorization)
        build_ms = (time.perf_counter() - started) * 1000
        latencies = []
        for index in range(query_count):
            query = HybridQuery(
                query_id=f"benchmark-query-{index:05d}",
                text=f"database deterministic case {index % max(1, size)}",
                seed_record_ids=(),
                include_unavailable=False,
                limit=10,
            )
            started = time.perf_counter()
            retrieve_hybrid(home, catalog, (), query)
            latencies.append((time.perf_counter() - started) * 1000)
    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95)))
    return {
        "catalog_entries": len(catalog.entries),
        "knowledge_records": size,
        "index_build_ms": float(f"{build_ms:.3f}"),
        "query_median_ms": float(f"{ordered[len(ordered) // 2]:.3f}"),
        "query_p95_ms": float(f"{ordered[p95_index]:.3f}"),
        "query_count": query_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--queries", type=int, default=20)
    args = parser.parse_args(argv)
    if any(size < 1 for size in args.sizes) or args.queries < 1:
        parser.error("sizes and queries must be positive")
    print(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark": "hybrid-retrieval-synthetic",
                "vector_dimensions": 192,
                "results": [measure(size, args.queries) for size in args.sizes],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

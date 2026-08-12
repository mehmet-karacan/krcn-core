"""Deterministic quality evaluation for local hybrid retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .dependency_retrieval import InformationRelation
from .hybrid_retrieval import HybridQuery, retrieve_hybrid
from .information_records import canonical_json
from .knowledge_catalog import InformationCatalog


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")


class RetrievalEvaluationError(ValueError):
    """Raised when a retrieval evaluation set is invalid."""


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    case_id: str
    query_text: str
    relevant_record_ids: tuple[str, ...]
    seed_record_ids: tuple[str, ...]


def load_retrieval_evaluation(repo_root: Path) -> tuple[RetrievalEvaluationCase, ...]:
    path = repo_root / "config" / "retrieval-evaluation.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetrievalEvaluationError("retrieval evaluation configuration is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "evaluation_id",
        "minimum_recall_at_five",
        "minimum_mrr",
        "cases",
    }:
        raise RetrievalEvaluationError("retrieval evaluation fields are invalid")
    if payload.get("schema_version") != 1 or payload.get("evaluation_id") != "phase-eight-hybrid":
        raise RetrievalEvaluationError("retrieval evaluation identity is invalid")
    for threshold_name in ("minimum_recall_at_five", "minimum_mrr"):
        threshold = payload.get(threshold_name)
        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not 0 <= float(threshold) <= 1
        ):
            raise RetrievalEvaluationError("retrieval evaluation threshold is invalid")
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list) or not cases_payload:
        raise RetrievalEvaluationError("retrieval evaluation cases are invalid")
    cases = []
    for item in cases_payload:
        if not isinstance(item, dict) or set(item) != {
            "case_id",
            "query_text",
            "relevant_record_ids",
            "seed_record_ids",
        }:
            raise RetrievalEvaluationError("retrieval evaluation case fields are invalid")
        case_id = item.get("case_id")
        query_text = item.get("query_text")
        relevant = item.get("relevant_record_ids")
        seeds = item.get("seed_record_ids")
        if not isinstance(case_id, str) or not IDENTIFIER.fullmatch(case_id):
            raise RetrievalEvaluationError("retrieval evaluation case id is invalid")
        if not isinstance(query_text, str) or not query_text.strip():
            raise RetrievalEvaluationError("retrieval evaluation query is invalid")
        if (
            not isinstance(relevant, list)
            or not relevant
            or any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in relevant)
            or len(set(relevant)) != len(relevant)
        ):
            raise RetrievalEvaluationError("retrieval evaluation relevant ids are invalid")
        if (
            not isinstance(seeds, list)
            or any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in seeds)
            or len(set(seeds)) != len(seeds)
        ):
            raise RetrievalEvaluationError("retrieval evaluation seed ids are invalid")
        cases.append(
            RetrievalEvaluationCase(
                case_id,
                query_text,
                tuple(relevant),
                tuple(seeds),
            )
        )
    if len({item.case_id for item in cases}) != len(cases):
        raise RetrievalEvaluationError("retrieval evaluation case ids must be unique")
    return tuple(cases)


def evaluate_hybrid_retrieval(
    data_root: Path,
    catalog: InformationCatalog,
    relations: Iterable[InformationRelation],
    cases: Iterable[RetrievalEvaluationCase],
) -> dict[str, object]:
    evaluations = []
    elapsed_values = []
    for case in cases:
        query = HybridQuery(
            query_id=case.case_id,
            text=case.query_text,
            seed_record_ids=case.seed_record_ids,
            include_unavailable=False,
            limit=5,
        )
        started = time.perf_counter()
        result = retrieve_hybrid(data_root, catalog, relations, query)
        elapsed_values.append((time.perf_counter() - started) * 1000)
        ranked = [item.entry.record.record_id for item in result.hits]
        relevant = set(case.relevant_record_ids)
        recalled = len(relevant & set(ranked)) / len(relevant)
        first_rank = next(
            (index for index, record_id in enumerate(ranked, 1) if record_id in relevant),
            None,
        )
        reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
        evaluations.append(
            {
                "case_id": case.case_id,
                "recall_at_five": float(f"{recalled:.6f}"),
                "reciprocal_rank": float(f"{reciprocal_rank:.6f}"),
                "top_record_id": ranked[0] if ranked else None,
            }
        )
    if not evaluations:
        raise RetrievalEvaluationError("retrieval evaluation set is empty")
    recall = sum(float(item["recall_at_five"]) for item in evaluations) / len(evaluations)
    mrr = sum(float(item["reciprocal_rank"]) for item in evaluations) / len(evaluations)
    identity = {
        "catalog_digest": catalog.catalog_digest,
        "cases": evaluations,
        "recall_at_five": float(f"{recall:.6f}"),
        "mean_reciprocal_rank": float(f"{mrr:.6f}"),
    }
    sorted_elapsed = sorted(elapsed_values)
    p95_index = min(len(sorted_elapsed) - 1, math_ceil(0.95 * len(sorted_elapsed)) - 1)
    return {
        "schema_version": 1,
        **identity,
        "result_digest": hashlib.sha256(canonical_json(identity)).hexdigest(),
        "case_count": len(evaluations),
        "latency_ms": {
            "median": float(f"{sorted_elapsed[len(sorted_elapsed) // 2]:.3f}"),
            "p95": float(f"{sorted_elapsed[p95_index]:.3f}"),
        },
        "remote": False,
    }


def math_ceil(value: float) -> int:
    integer = int(value)
    return integer if value == integer else integer + 1

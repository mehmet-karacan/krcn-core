from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.execution_observability import (  # noqa: E402
    ExecutionObservabilityError,
    build_execution_trace,
    parse_execution_trace,
    parse_status_projection,
    project_execution_status,
)


def _schema(name: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _trace(**overrides: object):
    arguments: dict[str, object] = {
        "correlation_id": "corr-1",
        "request_id": "request-1",
        "client_id": "codex-desktop",
        "project_id": "gpu-fusion",
        "work_item_id": "request-893614",
        "intent_digest": "a" * 64,
        "context_digest": "b" * 64,
        "plan_id": "c" * 64,
        "approval_envelope_id": "approval-1",
        "delegation_mode": "native-parallel",
        "model_assignment_ids": ["analysis-primary", "verifier-primary"],
        "queue_ids": ["queue-analysis", "queue-verifier"],
        "agent_execution_ids": ["execution-analysis", "execution-verifier"],
        "verification_id": "verification-1",
        "evidence_digest": "d" * 64,
        "status": "completed",
        "started_at": "2026-08-15T14:00:00+03:00",
        "ended_at": "2026-08-15T14:00:01.500+03:00",
        "token_usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 25,
            "cache_write_tokens": 5,
        },
        "estimated_cost": {
            "amount_microunits": 3200,
            "currency": "USD",
        },
        "retry_count": 1,
        "cache_hit": False,
    }
    arguments.update(overrides)
    return build_execution_trace(**arguments)


class ExecutionTraceTests(unittest.TestCase):
    def test_trace_round_trip_matches_schema_and_carries_bounded_metrics(self) -> None:
        trace = _trace()
        payload = trace.as_dict()

        self.assertEqual(
            [],
            list(
                Draft202012Validator(_schema("execution-trace.schema.json"))
                .iter_errors(payload)
            ),
        )
        self.assertEqual(1500, payload["duration_ms"])
        self.assertEqual(150, payload["token_usage"]["total_tokens"])
        self.assertTrue(payload["estimated_cost"]["is_estimate"])
        self.assertFalse(payload["grants_authority"])
        self.assertFalse(payload["contains_raw_payload"])
        self.assertFalse(payload["contains_physical_paths"])
        self.assertEqual(trace, parse_execution_trace(payload))

    def test_running_trace_has_no_invented_end_or_cost(self) -> None:
        payload = _trace(
            status="running",
            ended_at=None,
            estimated_cost=None,
            token_usage=None,
        ).as_dict()

        self.assertIsNone(payload["ended_at"])
        self.assertIsNone(payload["duration_ms"])
        self.assertIsNone(payload["estimated_cost"])
        self.assertEqual(0, payload["token_usage"]["total_tokens"])

    def test_trace_rejects_paths_secrets_invalid_totals_and_digest_tamper(self) -> None:
        with self.assertRaisesRegex(ExecutionObservabilityError, "physical path"):
            _trace(failure_code="D:/private/failure")
        with self.assertRaises(ExecutionObservabilityError):
            _trace(client_id="api_key=not-real")

        payload = _trace().as_dict()
        payload["token_usage"] = dict(payload["token_usage"])
        payload["token_usage"]["total_tokens"] = 999
        with self.assertRaisesRegex(ExecutionObservabilityError, "total is invalid"):
            parse_execution_trace(payload)

        payload = _trace().as_dict()
        payload["retry_count"] = 2
        with self.assertRaisesRegex(ExecutionObservabilityError, "content or digest"):
            parse_execution_trace(payload)

        for field in ("grants_authority", "contains_raw_payload", "contains_physical_paths"):
            payload = _trace().as_dict()
            payload[field] = True
            with self.subTest(field=field), self.assertRaises(ExecutionObservabilityError):
                parse_execution_trace(payload)

    def test_trace_rejects_boolean_metrics_and_negative_duration(self) -> None:
        with self.assertRaisesRegex(ExecutionObservabilityError, "non-negative integer"):
            _trace(retry_count=True)
        with self.assertRaisesRegex(ExecutionObservabilityError, "must not precede"):
            _trace(ended_at="2026-08-15T10:59:59Z")


class StatusProjectionTests(unittest.TestCase):
    def test_projection_uses_one_canonical_status_without_raw_domain_states(self) -> None:
        trace = _trace()
        projection = project_execution_status(
            correlation_id="corr-1",
            project_id="gpu-fusion",
            work_item_id="request-893614",
            source_statuses={
                "work": "active",
                "queue": "completed",
                "orchestration": "verifying",
            },
            summary="Bağımsız doğrulama bekleniyor",
            next_action="Verifier sonucunu bağla",
            reason_codes=["verification-pending"],
            trace_digest=trace.as_dict()["trace_digest"],
            updated_at="2026-08-15T11:01:30Z",
        )
        payload = projection.as_dict()

        self.assertEqual("awaiting-verification", payload["status"])
        self.assertNotIn("source_statuses", payload)
        self.assertEqual(
            [],
            list(
                Draft202012Validator(_schema("status-projection.schema.json"))
                .iter_errors(payload)
            ),
        )
        self.assertEqual(projection, parse_status_projection(payload))

    def test_failed_blocked_stale_and_degraded_precedence_is_deterministic(self) -> None:
        common = {
            "correlation_id": "corr-1",
            "project_id": "gpu-fusion",
            "work_item_id": "request-893614",
            "summary": "Durum hesaplandı",
            "updated_at": "2026-08-15T11:01:30Z",
        }
        failed = project_execution_status(
            **common,
            source_statuses={"queue": "failed", "work": "active"},
            degraded=True,
            derived_stale=True,
        )
        stale = project_execution_status(
            **common,
            source_statuses={"queue": "completed", "work": "completed"},
            derived_stale=True,
        )
        degraded = project_execution_status(
            **common,
            source_statuses={"queue": "running", "work": "active"},
            degraded=True,
        )

        self.assertEqual("failed", failed.as_dict()["status"])
        self.assertEqual("derived-stale", stale.as_dict()["status"])
        self.assertEqual("degraded", degraded.as_dict()["status"])

    def test_projection_rejects_unknown_states_paths_and_digest_tamper(self) -> None:
        common = {
            "correlation_id": "corr-1",
            "project_id": "gpu-fusion",
            "work_item_id": "request-893614",
            "summary": "Durum hesaplandı",
            "updated_at": "2026-08-15T11:01:30Z",
        }
        with self.assertRaisesRegex(ExecutionObservabilityError, "unsupported state"):
            project_execution_status(
                **common,
                source_statuses={"queue": "mystery"},
            )
        with self.assertRaisesRegex(ExecutionObservabilityError, "physical path"):
            project_execution_status(
                **common,
                source_statuses={"queue": "running"},
                next_action="Read /" + "home/user/private.txt",
            )

        payload = project_execution_status(
            **common,
            source_statuses={"queue": "running"},
        ).as_dict()
        payload["summary"] = "Değiştirildi"
        with self.assertRaisesRegex(ExecutionObservabilityError, "digest"):
            parse_status_projection(payload)

        for status, field in (
            ("degraded", "degraded"),
            ("derived-stale", "derived_stale"),
        ):
            payload = project_execution_status(
                **common,
                source_statuses={"queue": "running"},
            ).as_dict()
            payload["status"] = status
            payload[field] = False
            with self.subTest(status=status), self.assertRaisesRegex(
                ExecutionObservabilityError, "requires"
            ):
                parse_status_projection(payload)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "benchmark_runtime_queue.py"
SPEC = importlib.util.spec_from_file_location("benchmark_runtime_queue", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
BENCHMARK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BENCHMARK
SPEC.loader.exec_module(BENCHMARK)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class QueueSuitabilityTests(unittest.TestCase):
    def test_policy_and_baseline_follow_their_schemas(self) -> None:
        pairs = (
            (
                "schemas/queue-suitability-policy.schema.json",
                "config/queue-suitability.json",
            ),
            (
                "schemas/queue-suitability-baseline.schema.json",
                ".ai/queue-suitability-baseline.json",
            ),
        )
        for schema_ref, document_ref in pairs:
            with self.subTest(document=document_ref):
                validator = Draft202012Validator(load_json(REPO_ROOT / schema_ref))
                self.assertEqual(
                    [],
                    list(validator.iter_errors(load_json(REPO_ROOT / document_ref))),
                )

    def test_baseline_is_bound_to_current_runtime_sources(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai/queue-suitability-baseline.json")
        expected = {
            "runtime_source_digest": REPO_ROOT / "src/krcn_core/agent_runtime.py",
            "scheduler_policy_digest": REPO_ROOT / "config/runtime-scheduler.json",
        }
        for field, path in expected.items():
            with self.subTest(field=field):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    baseline[field],
                )

    def test_reference_profiles_pass_and_external_candidates_are_deferred(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai/queue-suitability-baseline.json")
        self.assertTrue(all(item["thresholds_passed"] for item in baseline["observed"]))
        decisions = {
            item["backend_id"]: item for item in baseline["candidate_decision"]
        }
        self.assertEqual("retained", decisions["sqlite"]["adoption_status"])
        for backend_id in (
            "redis-streams",
            "nats-jetstream",
            "postgresql-queue",
        ):
            self.assertEqual("not-run", decisions[backend_id]["measurement_status"])
            self.assertEqual("deferred", decisions[backend_id]["adoption_status"])

    def test_tiny_real_queue_measurement_preserves_correctness(self) -> None:
        profiles = [
            {
                "profile_id": "tiny-one",
                "item_count": 4,
                "project_count": 1,
                "worker_count": 1,
                "maximum_claim_p95_ms": 2000,
                "minimum_throughput_per_second": 0.1,
            },
            {
                "profile_id": "tiny-two",
                "item_count": 8,
                "project_count": 2,
                "worker_count": 2,
                "maximum_claim_p95_ms": 2000,
                "minimum_throughput_per_second": 0.1,
            },
        ]
        result = BENCHMARK.benchmark(
            REPO_ROOT,
            execution_mode="threads",
            profiles=profiles,
        )
        self.assertTrue(all(result["correctness"].values()))
        self.assertEqual([4, 8], [item["item_count"] for item in result["observed"]])
        self.assertTrue(all(item["thresholds_passed"] for item in result["observed"]))

    def test_benchmark_has_no_external_backend_dependency(self) -> None:
        source = TOOL_PATH.read_text(encoding="utf-8")
        for package in ("import redis", "import nats", "import psycopg"):
            with self.subTest(package=package):
                self.assertNotIn(package, source)
        policy = BENCHMARK.load_policy(REPO_ROOT)
        self.assertFalse(policy["external_backend_adoption_allowed"])


if __name__ == "__main__":
    unittest.main()

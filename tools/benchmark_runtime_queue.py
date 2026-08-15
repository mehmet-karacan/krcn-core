#!/usr/bin/env python3
"""Measure the existing local SQLite runtime queue without external services."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_runtime import (  # noqa: E402
    AgentRuntimeError,
    AgentRuntimeQueue,
    load_scheduler_policy,
)


STATE_CHANGED = "runtime queue changed after planning"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile)))
    return float(f"{ordered[index]:.3f}")


def load_policy(repo_root: Path) -> dict[str, object]:
    payload = json.loads(
        (repo_root / "config" / "queue-suitability.json").read_text(
            encoding="utf-8"
        )
    )
    required = {
        "schema_ref",
        "schema_version",
        "policy_id",
        "baseline_backend",
        "profiles",
        "candidates",
        "migration_triggers",
        "external_backend_adoption_allowed",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("queue suitability policy fields are invalid")
    if (
        payload["schema_ref"]
        != "schemas/queue-suitability-policy.schema.json"
        or payload["schema_version"] != 1
        or payload["policy_id"] != "queue-suitability-v1"
        or payload["baseline_backend"] != "sqlite"
        or payload["external_backend_adoption_allowed"] is not False
    ):
        raise ValueError("queue suitability policy identity is invalid")
    profiles = payload["profiles"]
    candidates = payload["candidates"]
    if not isinstance(profiles, list) or not isinstance(candidates, list):
        raise ValueError("queue suitability collections are invalid")
    if len({item.get("profile_id") for item in profiles if isinstance(item, dict)}) != len(profiles):
        raise ValueError("queue suitability profile identities are not unique")
    if len({item.get("backend_id") for item in candidates if isinstance(item, dict)}) != len(candidates):
        raise ValueError("queue suitability backend identities are not unique")
    return payload


def _enqueue_arguments(index: int, project_id: str) -> dict[str, object]:
    identity = {
        "work_item_id": f"benchmark-work-{index:05d}",
        "task_id": f"benchmark-run-{index:05d}",
        "step_id": "measure",
    }
    idempotency_key = _digest(identity)
    return {
        "project_id": project_id,
        "work_item_id": identity["work_item_id"],
        "work_item_revision": 1,
        "work_item_digest": _digest({"work": index}),
        "task_id": identity["task_id"],
        "parent_task_id": None,
        "plan_id": "a" * 64,
        "step_id": identity["step_id"],
        "required_role": "worker",
        "required_capabilities": ["benchmark-read"],
        "side_effects": ["read"],
        "resource_refs": [f"task:{project_id}:{identity['work_item_id']}"],
        "idempotency_key": idempotency_key,
        "queue_id": "queue-" + idempotency_key[:24],
        "max_attempts": 3,
    }


def _apply_with_retry(
    queue: AgentRuntimeQueue,
    action: str,
    arguments: Mapping[str, object],
    *,
    retry_limit: int = 1000,
) -> tuple[dict[str, object], int]:
    retries = 0
    while retries <= retry_limit:
        expected = queue.state_digest()
        try:
            return queue.apply(action, arguments, expected), retries
        except AgentRuntimeError as exc:
            if str(exc) != STATE_CHANGED:
                raise
            retries += 1
    raise RuntimeError("runtime queue contention retry limit was exceeded")


def _consume_worker(
    repo_root: str,
    data_root: str,
    owner_index: int,
    project_ids: list[str],
) -> dict[str, object]:
    policy = load_scheduler_policy(Path(repo_root))
    queues = [
        AgentRuntimeQueue(Path(data_root), project_id, policy)
        for project_id in project_ids
    ]
    claim_latencies: list[float] = []
    retries = 0
    completed = 0
    owner_digest = hashlib.sha256(
        f"benchmark-owner-{owner_index}".encode("utf-8")
    ).hexdigest()
    ordered_queues = queues[owner_index % len(queues):] + queues[:owner_index % len(queues)]
    while True:
        claimed_in_cycle = False
        for queue in ordered_queues:
            started = time.perf_counter()
            claim, claim_retries = _apply_with_retry(
                queue,
                "claim",
                {
                    "project_id": queue.project_id,
                    "owner_digest": owner_digest,
                    "worker_role": "worker",
                    "capability_refs": ["benchmark-read"],
                    "lease_seconds": 60,
                },
            )
            claim_latencies.append((time.perf_counter() - started) * 1000)
            retries += claim_retries
            if not claim["claimed"]:
                continue
            claimed_in_cycle = True
            complete, complete_retries = _apply_with_retry(
                queue,
                "complete",
                {
                    "project_id": queue.project_id,
                    "queue_id": claim["queue_id"],
                    "lease_id": claim["lease_id"],
                    "owner_digest": owner_digest,
                    "fencing_token": claim["fencing_token"],
                    "evidence_digest": _digest(
                        {"queue_id": claim["queue_id"], "status": "verified"}
                    ),
                },
            )
            retries += complete_retries
            if complete["status"] != "completed":
                raise RuntimeError("runtime queue benchmark completion failed")
            completed += 1
        if not claimed_in_cycle:
            break
    return {
        "completed": completed,
        "claim_latencies": claim_latencies,
        "state_retry_count": retries,
    }


def _thread_target(
    output: Queue,
    repo_root: str,
    data_root: str,
    owner_index: int,
    project_ids: list[str],
) -> None:
    try:
        output.put(
            _consume_worker(repo_root, data_root, owner_index, project_ids)
        )
    except Exception as exc:  # pragma: no cover - surfaced to parent
        output.put({"error": f"{type(exc).__name__}: {exc}"})


def _process_target(
    output: multiprocessing.Queue,
    repo_root: str,
    data_root: str,
    owner_index: int,
    project_ids: list[str],
) -> None:
    try:
        output.put(
            _consume_worker(repo_root, data_root, owner_index, project_ids)
        )
    except Exception as exc:  # pragma: no cover - surfaced to parent
        output.put({"error": f"{type(exc).__name__}: {exc}"})


def _run_workers(
    repo_root: Path,
    data_root: Path,
    worker_count: int,
    execution_mode: str,
    project_ids: list[str],
) -> list[dict[str, object]]:
    if execution_mode == "threads":
        output: Queue = Queue()
        workers = [
            threading.Thread(
                target=_thread_target,
                args=(
                    output,
                    str(repo_root),
                    str(data_root),
                    index,
                    project_ids,
                ),
                daemon=True,
            )
            for index in range(worker_count)
        ]
    else:
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        workers = [
            context.Process(
                target=_process_target,
                args=(
                    output,
                    str(repo_root),
                    str(data_root),
                    index,
                    project_ids,
                ),
            )
            for index in range(worker_count)
        ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(120)
        if worker.is_alive():
            worker.terminate()
            worker.join()
            raise RuntimeError("runtime queue benchmark worker timed out")
        if getattr(worker, "exitcode", 0) not in (None, 0):
            raise RuntimeError("runtime queue benchmark worker failed")
    results = [output.get(timeout=5) for _ in workers]
    errors = [result["error"] for result in results if "error" in result]
    if errors:
        raise RuntimeError("; ".join(str(error) for error in errors))
    return results


def measure_profile(
    repo_root: Path,
    profile: Mapping[str, object],
    *,
    execution_mode: str,
) -> dict[str, object]:
    policy = load_scheduler_policy(repo_root)
    with tempfile.TemporaryDirectory() as directory:
        data_root = Path(directory) / ".krcn"
        project_count = int(profile["project_count"])
        project_ids = [
            f"queue-benchmark-{index:02d}" for index in range(project_count)
        ]
        queues = [
            AgentRuntimeQueue(data_root, project_id, policy)
            for project_id in project_ids
        ]
        enqueue_latencies: list[float] = []
        for index in range(int(profile["item_count"])):
            queue = queues[index % len(queues)]
            started = time.perf_counter()
            _, retries = _apply_with_retry(
                queue,
                "enqueue",
                _enqueue_arguments(index, queue.project_id),
            )
            if retries:
                raise RuntimeError("sequential enqueue unexpectedly contended")
            enqueue_latencies.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        results = _run_workers(
            repo_root,
            data_root,
            int(profile["worker_count"]),
            execution_mode,
            project_ids,
        )
        elapsed = time.perf_counter() - started
        completed = sum(int(result["completed"]) for result in results)
        if completed != int(profile["item_count"]):
            raise RuntimeError("runtime queue benchmark did not complete every item")
        claim_latencies = [
            float(value)
            for result in results
            for value in result["claim_latencies"]
        ]
        statuses = [queue.status() for queue in queues]
        thresholds_passed = (
            _percentile(claim_latencies, 0.95)
            <= float(profile["maximum_claim_p95_ms"])
            and completed / elapsed
            >= float(profile["minimum_throughput_per_second"])
        )
        return {
            "profile_id": profile["profile_id"],
            "item_count": completed,
            "project_count": profile["project_count"],
            "worker_count": profile["worker_count"],
            "enqueue_p95_ms": _percentile(enqueue_latencies, 0.95),
            "claim_p50_ms": float(
                f"{statistics.median(claim_latencies):.3f}"
            ),
            "claim_p95_ms": _percentile(claim_latencies, 0.95),
            "throughput_per_second": float(f"{completed / elapsed:.3f}"),
            "state_retry_count": sum(
                int(result["state_retry_count"]) for result in results
            ),
            "database_bytes": sum(queue.path.stat().st_size for queue in queues),
            "thresholds_passed": thresholds_passed,
            "integrity_verified": all(
                status["integrity_verified"] for status in statuses
            ),
        }


def verify_correctness(repo_root: Path) -> dict[str, bool]:
    policy = load_scheduler_policy(repo_root)
    with tempfile.TemporaryDirectory() as directory:
        data_root = Path(directory) / ".krcn"
        first = AgentRuntimeQueue(
            data_root,
            "correctness-benchmark",
            policy,
            clock=lambda: 1000.0,
        )
        item = _enqueue_arguments(1, "correctness-benchmark")
        first.apply("enqueue", item, first.state_digest())
        owner_one = hashlib.sha256(b"owner-one").hexdigest()
        claim_one = first.apply(
            "claim",
            {
                "project_id": "correctness-benchmark",
                "owner_digest": owner_one,
                "worker_role": "worker",
                "capability_refs": ["benchmark-read"],
                "lease_seconds": 10,
            },
            first.state_digest(),
        )
        expired = AgentRuntimeQueue(
            data_root,
            "correctness-benchmark",
            policy,
            clock=lambda: 1011.0,
        )
        recovery = expired.apply(
            "recover",
            {"project_id": "correctness-benchmark"},
            expired.state_digest(),
        )
        owner_two = hashlib.sha256(b"owner-two").hexdigest()
        claim_two = expired.apply(
            "claim",
            {
                "project_id": "correctness-benchmark",
                "owner_digest": owner_two,
                "worker_role": "worker",
                "capability_refs": ["benchmark-read"],
                "lease_seconds": 10,
            },
            expired.state_digest(),
        )
        stale_rejected = False
        try:
            expired.apply(
                "complete",
                {
                    "project_id": "correctness-benchmark",
                    "queue_id": claim_one["queue_id"],
                    "lease_id": claim_one["lease_id"],
                    "owner_digest": owner_one,
                    "fencing_token": claim_one["fencing_token"],
                    "evidence_digest": "b" * 64,
                },
                expired.state_digest(),
            )
        except AgentRuntimeError:
            stale_rejected = True
        expired.apply(
            "complete",
            {
                "project_id": "correctness-benchmark",
                "queue_id": claim_two["queue_id"],
                "lease_id": claim_two["lease_id"],
                "owner_digest": owner_two,
                "fencing_token": claim_two["fencing_token"],
                "evidence_digest": "c" * 64,
            },
            expired.state_digest(),
        )
        backup_root = Path(directory) / "backup"
        shutil.copytree(data_root, backup_root)
        restored = AgentRuntimeQueue(
            backup_root,
            "correctness-benchmark",
            policy,
            clock=lambda: 1011.0,
        ).status()
        current = expired.status()
        return {
            "lease_recovery_verified": recovery["recovered_count"] == 1,
            "stale_fencing_rejected": stale_rejected,
            "integrity_verified": current["integrity_verified"] is True,
            "backup_restore_verified": (
                restored["integrity_verified"] is True
                and restored["counts"] == current["counts"]
            ),
        }


def benchmark(
    repo_root: Path,
    *,
    execution_mode: str = "processes",
    profiles: list[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    if execution_mode not in {"processes", "threads"}:
        raise ValueError("queue benchmark execution mode is invalid")
    policy = load_policy(repo_root)
    selected_profiles = profiles or policy["profiles"]
    observed = [
        measure_profile(
            repo_root,
            profile,
            execution_mode=execution_mode,
        )
        for profile in selected_profiles
    ]
    for result in observed:
        result.pop("integrity_verified")
    candidates = [
        {
            "backend_id": item["backend_id"],
            "measurement_status": item["measurement_status"],
            "adoption_status": item["adoption_status"],
        }
        for item in policy["candidates"]
    ]
    return {
        "schema_ref": "schemas/queue-suitability-baseline.schema.json",
        "schema_version": 1,
        "benchmark_id": "runtime-queue-sqlite-v1",
        "policy_id": policy["policy_id"],
        "runtime_source_digest": _file_digest(
            repo_root / "src" / "krcn_core" / "agent_runtime.py"
        ),
        "scheduler_policy_digest": _file_digest(
            repo_root / "config" / "runtime-scheduler.json"
        ),
        "measurement_scope": "local synthetic reference workload",
        "execution_mode": execution_mode,
        "observed": observed,
        "correctness": verify_correctness(repo_root),
        "candidate_decision": candidates,
        "decision": "retain-sqlite-for-v1",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execution-mode",
        choices=("processes", "threads"),
        default="processes",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            benchmark(REPO_ROOT, execution_mode=args.execution_mode),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

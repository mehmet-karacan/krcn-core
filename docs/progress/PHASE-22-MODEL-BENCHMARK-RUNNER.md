# Phase 22: Model benchmark runner

Status: implementation complete in isolated package; shared application/CLI
integration intentionally deferred.

## Delivered

- offline-first injected-adapter benchmark execution;
- strict execution profile with harness/model/provider-route/reasoning/
  quantization/environment and independent-verifier provenance;
- exact run plan bound to suite, source, workload, case, inventory, health,
  profile, repetition, timeout, and provider authorization identities;
- health-passed, workload, fixture policy, provider, and confidence-safe sample
  gates;
- five-or-more repeated trials with deterministic identities;
- parse, format, evidence, verifier, timeout, retry, correction, token, latency,
  and cost evidence;
- deterministic mean, median, p95, population variance, totals, and cost per
  verifier-approved result;
- fail-closed rejection of mixed profiles, stale inputs, tampered plans/results,
  raw fields, secrets, and physical paths;
- existing model benchmark result and runtime observation compatibility output;
- no store mutation, provider discovery, implicit provider call, network
  dependency, or external package.

## Files

- `src/krcn_core/model_benchmark_runner.py`
- `config/model-benchmark-runner.json`
- `schemas/model-benchmark-execution-profile.schema.json`
- `schemas/model-benchmark-run-plan.schema.json`
- `schemas/model-benchmark-trial-result.schema.json`
- `schemas/model-benchmark-aggregate-result.schema.json`
- `tests/test_model_benchmark_runner.py`
- `docs/specifications/MODEL-BENCHMARK-RUNNER.md`

## Verification

The focused tests cover:

- deterministic local fake-adapter execution and statistics;
- one-shot and sub-threshold sample rejection;
- mandatory current `health-passed` evidence;
- remote execution without approval rejection;
- remote `local-only` fixture rejection;
- mixed-profile pooling rejection;
- exact-plan tamper rejection;
- raw output, secret, and physical-path rejection without reflected values;
- independent verifier execution and model-family requirements;
- compatibility benchmark/runtime observation generation without persistence.

Application routing, CLI commands, repository-context catalog registration, and
durable record writes are not part of this isolated package. They remain behind
their own exact-plan review and were not modified.

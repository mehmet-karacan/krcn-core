# Phase 22: Model benchmark runner

Status: implementation and fail-closed application/CLI integration complete.

## Delivered

- offline-first injected durable-host benchmark execution;
- store-only authoritative suite, inventory, health, capability-profile, and
  source-state resolution;
- durable exactly-once claim before any trial and digest-bound receipt after it;
- terminal failure receipts for malformed outcomes/runner validation, canonical
  cost-free failure replay, and explicit recovery-required pending claims;
- strict execution profile with harness/model/provider-route/reasoning/
  quantization/environment and independent-verifier provenance;
- exact run plan bound to suite, source, workload, case, inventory, health,
  profile, host, repetition, timeout, and provider request/session/approval/
  authorization identities;
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
- `schemas/model-benchmark-execution-claim.schema.json`
- `schemas/model-benchmark-execution-receipt.schema.json`
- `schemas/model-benchmark-run-plan.schema.json`
- `schemas/model-benchmark-trial-result.schema.json`
- `schemas/model-benchmark-aggregate-result.schema.json`
- `tests/test_model_benchmark_runner.py`
- `docs/specifications/MODEL-BENCHMARK-RUNNER.md`

## Verification

The focused tests cover:

- deterministic local durable fake-host execution and statistics;
- empty authoritative store and stale source/profile rejection;
- replay rejection without a second trial call;
- malformed first outcome recorded as one terminal failure receipt, with a
  deterministic second-call no-op and no additional trial/cost;
- interrupted pending claim rejection with explicit recovery required;
- provider approval swap rejection before host claim;
- one-shot and sub-threshold sample rejection;
- mandatory current `health-passed` evidence;
- remote execution without approval rejection;
- remote `local-only` fixture rejection;
- mixed-profile pooling rejection;
- exact-plan tamper rejection;
- raw output, secret, and physical-path rejection without reflected values;
- independent verifier execution and model-family requirements;
- compatibility benchmark/runtime observation generation without persistence.

Application and request-file CLI routing use only authoritative record identities.
The default CLI and incomplete hosts fail closed. Execution claims and receipts
are owned by the injected durable host; benchmark results remain non-persisted
until the existing evidence-write exact-plan boundary is invoked separately.

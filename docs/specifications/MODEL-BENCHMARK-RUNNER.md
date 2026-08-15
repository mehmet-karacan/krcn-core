# Model benchmark runner

## Purpose

The model benchmark runner executes an existing project micro benchmark suite
through one explicitly injected durable execution host. It adds repeated-run evidence and
execution provenance without discovering a provider, calling a provider during
planning, persisting records, or granting authority.

It reuses these authoritative inputs:

- `model-benchmark-suite.schema.json` for project, source, workload, case, and
  fixture identity;
- `model-inventory-record.schema.json` for the declared model and provider;
- `model-health-record.schema.json` for current `health-passed` eligibility;
- the provider gate's session-scoped authorization for remote execution;
- `model-benchmark-result.schema.json` and
  `model-runtime-observation.schema.json` as compatibility outputs.

The application route accepts only project, suite, and model identities. It
resolves the suite, model inventory, model health, current capability profile,
and source state from `LocalWorkspaceStore`; caller payloads cannot substitute
those records. The runner does not replace suite construction, model health,
provider policy, model assignment, or evidence persistence.

## Contracts

### Execution profile

`schemas/model-benchmark-execution-profile.schema.json` binds all variables
that may make two runs incomparable:

- client and harness identity and harness revision;
- declared model and inventory digest plus explicit model revision and family;
- provider and logical provider route, without endpoint or credential values;
- quantization and reasoning configuration;
- environment digest, without a physical path;
- worker execution identity and an independently attributed verifier execution
  and model family.

Worker and verifier execution references must differ. Their model families must
also differ. A profile digest covers every comparison-relevant field.

### Exact run plan

`prepare_model_benchmark_run` is read-only. It performs no host discovery and
no provider call. It rejects:

- disabled or non-`health-passed` models;
- stale inventory, health, suite, workload, case, source, or execution-profile
  bindings;
- a workload unsupported by the model;
- fewer than five confidence-safe repetitions;
- a remote run without exact provider authorization;
- a remote run of a `local-only` fixture;
- local runs carrying irrelevant provider authorization;
- timeout or repetition limits outside policy.

The plan binds a deterministic repetition identity for every trial. The
application requires the exact `plan_digest`; the bound runner additionally
checks its deterministic `plan_id`. The runner reparses the plan and
all store-resolved current inputs before invoking the host, so stale or modified
state fails closed. The plan also binds the durable host digest and, for remote
models, request, session, approval, authorization-reference, and combined
authorization digests.

### Trial result

The injected host receives a source-content-free structural request. Its
model-specific trial adapter must
return only the strict outcome fields accepted by the runner. The persisted form
contains metrics and provenance, never prompt, response, source text, endpoint,
credential, secret, or physical path values.

Each repetition records:

- parse, output-format, evidence, and independent-verifier outcomes;
- timeout and normalized failure category;
- quality and reliability basis points;
- latency, input/output tokens, retries, human corrections;
- estimated and actual cost microunits;
- verifier execution and model-family attribution;
- deterministic plan, profile, suite, source, workload, case, inventory, and
  trial digests.

The host may report `TimeoutError`, which becomes a sanitized timeout result.
Other host/adapter exceptions become sanitized `adapter-error` trials and do not
reflect exception text or prevent the remaining planned repetitions.
Hosts that invoke an external process or provider remain responsible for
enforcing a hard cancellation deadline; the runner also rejects a returned
latency beyond the reviewed plan timeout.

### Aggregate result

`aggregate_model_benchmark_trials` accepts only the exact ordered trial set from
one plan. Different execution profiles, suite/source/workload/case identities,
models, inventories, or trial sequences are never pooled.

Five samples are the minimum confidence-safe set. The aggregate includes
deterministically rounded mean, median, nearest-rank p95, and population variance
for quality, reliability, latency, total tokens, and estimated cost. It also
includes totals for tokens, retries, human corrections, estimated/actual cost,
and estimated cost per verifier-approved result.

A benchmark passes only when every trial is verifier-approved and every trial
meets the configured quality and reliability floors. This deliberately prevents
a high average from hiding an unsafe failed trial.

## Durable execution host and replay boundary

Plain callables are rejected because they cannot prove replay protection. An
execution host must expose a content-free descriptor declaring durable,
exactly-once claim-before-execution and receipt-after-execution semantics, plus
terminal-failure receipts, explicit pending-claim recovery, and no silent retry.
It exposes strict `get_claim`, `get_receipt`, `claim`, `run_trial`, `complete`,
and `complete_failure` operations. The host atomically
claims the plan digest before the first model call. A duplicate or incomplete
claim is resolved from the ledger before another trial can run. After all sanitized records are
built, the host durably stores a receipt bound to the claim, plan, aggregate,
host, and output digests.

If adapter output cannot pass strict parsing or subsequent runner validation,
the host records a terminal `failed` receipt bound to the claim, plan, host,
sanitized failure category, and deterministic failure digest. Replaying that
same plan returns the canonical failure record without another trial or cost.
A claimed plan with no terminal receipt is treated as an interrupted execution:
it returns `recovery-required` and cannot silently resume or retry. A retry must
therefore be represented by a separately reviewed plan identity rather than by
discarding or overwriting the original claim.

KRCN never imports, scans for, or selects hosts. The default CLI has no host and
returns `blocked`. A remote inventory record is not authority: the caller must supply an already verified
`ProviderAuthorization` whose provider, operation scope (`model-benchmark`),
request, session, approval identity, and authorization reference exactly match
the plan. Swapping only the approval at execution is rejected before host claim.

The host request contains identifiers, digests, output section names, fixture
policy, timeout, and the sanitized execution profile. It contains no prompt,
source content, output content, endpoint, credential, secret, or physical path.

## Compatibility and persistence

Successful `execute_model_benchmark_run` calls return `BenchmarkRunOutput` with:

- strict trial records;
- one strict aggregate record;
- a legacy-compatible model benchmark result using aggregate mean quality,
  mean reliability, p95 latency, and aggregate pass status;
- one legacy-compatible runtime observation per trial using actual cost only.
- the durable execution claim and completion receipt.

A terminal validation failure returns a sanitized `BenchmarkRunFailure` with
the plan, claim, failure receipt, empty result collections, and explicit
incomplete cost accounting. Application responses expose whether execution was
performed in the current call; durable failure replay reports `false`.

The runner does not write any of these records to a store. Existing exact-plan
evidence persistence remains a separate approval boundary. Estimated cost is
never presented as actual cost in compatibility observations.

## Public Python API

- `load_model_benchmark_runner_policy`
- `resolve_authoritative_benchmark_inputs`
- `build_benchmark_execution_host_descriptor`
- `validate_benchmark_execution_host`
- `build_benchmark_execution_claim`
- `parse_benchmark_execution_claim`
- `build_benchmark_execution_receipt`
- `parse_benchmark_execution_receipt`
- `build_execution_authorization_digest`
- `build_benchmark_execution_profile`
- `parse_benchmark_execution_profile`
- `prepare_model_benchmark_run`
- `prepare_model_benchmark_run_from_store`
- `parse_model_benchmark_run_plan`
- `execute_model_benchmark_run`
- `execute_model_benchmark_run_from_store`
- `parse_model_benchmark_trial_result`
- `aggregate_model_benchmark_trials`
- `parse_model_benchmark_aggregate_result`
- `BenchmarkRunOutput.as_dict`
- `BenchmarkRunFailure.as_dict`

The application and request-file CLI routes are integrated. They resolve all
authoritative benchmark inputs from the store and remain blocked when a durable
execution host is unavailable.

# Model benchmark runner

## Purpose

The model benchmark runner executes an existing project micro benchmark suite
through one explicitly injected adapter. It adds repeated-run evidence and
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

The runner does not replace suite construction, model health, provider policy,
model assignment, or evidence persistence.

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

`prepare_model_benchmark_run` is read-only. It performs no adapter discovery and
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

The plan binds a deterministic repetition identity for every trial. A caller
must pass the exact `plan_id` back at execution. The runner reparses the plan and
all current inputs, including the explicitly supplied current source digest,
before invoking the adapter, so stale or modified state fails closed.

### Trial result

The injected adapter receives a source-content-free structural request. It must
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

An adapter may raise `TimeoutError`, which becomes a sanitized timeout result.
Other adapter exceptions become sanitized `adapter-error` trials and do not
reflect exception text or prevent the remaining planned repetitions.
Adapters that invoke an external process or provider remain responsible for
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

## Adapter boundary

The runner accepts a callable at execution time. It never imports, scans for, or
selects adapters. Local execution is therefore the default. A remote inventory
record is not authority: the caller must supply an already verified
`ProviderAuthorization` whose provider, operation scope (`model-benchmark`),
request identity, and approval reference exactly match the plan.

The adapter request contains identifiers, digests, output section names, fixture
policy, timeout, and the sanitized execution profile. It contains no prompt,
source content, output content, endpoint, credential, secret, or physical path.

## Compatibility and persistence

`execute_model_benchmark_run` returns `BenchmarkRunOutput` with:

- strict trial records;
- one strict aggregate record;
- a legacy-compatible model benchmark result using aggregate mean quality,
  mean reliability, p95 latency, and aggregate pass status;
- one legacy-compatible runtime observation per trial using actual cost only.

The runner does not write any of these records to a store. Existing exact-plan
evidence persistence remains a separate approval boundary. Estimated cost is
never presented as actual cost in compatibility observations.

## Public Python API

- `load_model_benchmark_runner_policy`
- `build_benchmark_execution_profile`
- `parse_benchmark_execution_profile`
- `prepare_model_benchmark_run`
- `parse_model_benchmark_run_plan`
- `execute_model_benchmark_run`
- `parse_model_benchmark_trial_result`
- `aggregate_model_benchmark_trials`
- `parse_model_benchmark_aggregate_result`
- `BenchmarkRunOutput.as_dict`

No CLI or application-service route is added in this phase. That integration
requires a separate reviewed change to the shared command surface.

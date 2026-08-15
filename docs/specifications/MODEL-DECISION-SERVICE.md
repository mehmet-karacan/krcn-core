# Model Decision Service

## Purpose

The Model Decision Service composes existing routing, inventory, health,
project benchmark, runtime observation, and dated price evidence into one
deterministic model assignment. It does not call a model or provider and it
never grants execution, provider, mutation, database, or project authority.

The service optimizes verified net value instead of model size alone. A
qualified candidate is scored from benchmark quality, observed success,
latency, and estimated monetary cost. The exact score inputs and exclusions
are digest-bound in the decision.

## Evidence lifecycle

Model inventory remains credential-free global user data. Health records,
project benchmark suites, benchmark results, and runtime observations remain
derived evidence. Price catalogs are dated local user records. KRCN Core ships
only the price schema and scoring policy; it does not embed vendor prices.

The following additional local collections are used:

- `model-price-catalogs`: global user data under `models/pricing`;
- `model-benchmark-results`: project-derived benchmark outcomes;
- `model-runtime-observations`: project-derived sanitized execution metrics.

Every evidence write uses an exact local mutation plan. A price catalog needs
the normal user-data approval. Derived records still require an exact
authorization, but no provider call is implied. Raw prompts, responses,
credentials, endpoints, source content, and physical paths are forbidden.

## Eligibility gates

A bound inventory model is eligible only when all applicable checks pass:

- the inventory record is enabled and supports the workload and client;
- health evidence matches the inventory and current health policy;
- health and benchmark timestamps are within policy age bounds;
- quarantine, cooldown, failed health, and failed benchmark states are
  excluded;
- the project benchmark result matches the current suite, case, and inventory
  digests;
- remote models have a non-expired local price entry;
- optional latency and money budgets are satisfied;
- known worker model references cannot be reused by a verifier decision.

Missing or stale evidence never becomes a fabricated score. When no qualified
candidate remains, `client-default` is returned as an explicit unscored
fallback. If the client default model identity is unknown, the assignment
records that degraded fact and the independent execution identity invariant
remains mandatory.

## Closed loop

`model.decide` selects one workload assignment from durable local evidence.
`model.decide-plan` evaluates every TaskPlan step, creates a distinct
step-bound assignment identifier, and applies known verifier model exclusion
automatically. A later sanitized runtime observation feeds success, verifier
pass, latency, tokens, and cost back into the next decision.

Historical observations influence success and latency only after the minimum
sample count is reached. Until then, the policy's neutral success prior and
current health/benchmark latency are used. This prevents one noisy execution
from immediately changing the route.

## Cost boundary

Estimated call cost is calculated in catalog microunits:

```text
fixed
+ ceil(input_tokens * input_price_per_million / 1_000_000)
+ ceil(output_tokens * output_price_per_million / 1_000_000)
```

Catalog currency is explicit, observed and expiry timestamps are mandatory,
and an expired catalog fails closed. The service does not fetch or infer a
price from environment configuration.

## Authority and portability

Decisions, assignments, benchmark results, observations, and catalogs carry
`grants_authority: false`. They are context and quality evidence only. Existing
provider approval, TaskPlan authorization, exact mutation, queue, fencing, and
independent verifier controls remain authoritative.

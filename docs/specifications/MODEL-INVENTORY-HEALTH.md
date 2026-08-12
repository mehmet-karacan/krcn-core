# Model inventory and health lifecycle

## Purpose

KRCN stores a credential-free inventory of models that a user can access through a client or provider. The inventory is global because the same model may later be evaluated independently for multiple projects and workload profiles.

Inventory and health are not model assignment. They answer two narrower questions:

1. Which declared models are eligible candidates?
2. Did a candidate respond correctly to the approved synthetic health probe?

Project-specific benchmark scores and workload assignments remain separate records in later stages.

## Inventory contract

Each inventory record contains a portable model reference, provider reference, provider model identifier, display name, modalities, supported workloads, client references, enabled state, revision, and semantic digest.

The record never contains credentials or endpoints. Credentials remain client-managed. An inventory entry grants no provider, mutation, database, or project authority.

Inventory records are user data under `.krcn/global/models/` in layout v2. They require an exact plan and explicit user approval. Model records are global-only and cannot be written into project capsules.

## Health contract

Health probes use a versioned synthetic suite. The first suite checks that the selected model or embedding endpoint accepts one synthetic request and returns the expected response shape. No project content is included.

A remote probe requires all of the following:

- a current enabled inventory record;
- a supported text or embedding modality;
- an available provider adapter;
- an exact action plan;
- a session-bound provider approval;
- a client-managed credential reference.

The persisted derived record includes timestamps, status booleans, latency, failure category, consecutive failure count, quarantine time, policy digest, inventory digest, and probe/result digests. Prompt text, response content, endpoint, and credential values are not persisted.

## Lifecycle

```text
candidate
  -> health-passed
  -> benchmark-eligible

candidate
  -> health-failed
  -> quarantined
  -> cooldown
  -> candidate
```

Two consecutive failures quarantine a model under the current policy. After the cooldown, the effective state returns to `candidate`; the model must be tested again before assignment. A changed inventory digest or health policy digest makes the previous health result stale.

Health results are derived data under `.krcn/global/derived/model-health/`. They can be rebuilt and do not require a user-data approval. The remote provider call still requires explicit approval.

## Safety boundaries

- Inventory discovery never implies provider permission.
- A successful health result never implies workload competence.
- A benchmark assignment never grants project or mutation authority.
- Disabled, quarantined, stale, or unsupported models are not assignment candidates.
- Health planning performs no remote call and resolves no credential.
- Persisted records contain no physical project path or project source content.

## CLI surface

```text
krcn model inventory --input <inventory.json>
krcn model inventory --input <inventory.json> --apply --expected-plan <plan-id> --approval-id <approval-id>
krcn model list
krcn model health <model-ref> --endpoint <endpoint> --retention-assumptions <text> --session-id <session-id>
krcn model health <model-ref> --endpoint <endpoint> --retention-assumptions <text> --session-id <session-id> --apply --expected-plan <plan-id> --approval-id <approval-id>
krcn model health-list
```

The health plan reports only whether an endpoint is present. It does not echo the endpoint.

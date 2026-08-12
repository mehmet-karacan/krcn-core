# Project model micro benchmark suites

## Purpose

KRCN derives one deterministic micro benchmark suite from each current project capability profile. The suite defines what should be evaluated for the project before any model is assigned to an agent workload.

The suite is a manifest, not a benchmark result. Building it performs no provider call, executes no project code, and stores no source text or prompt text.

## Input boundary

A suite can be built only when all of the following are current and consistent:

- complete project integration state;
- structured capability profile with complete coverage;
- source binding and binding revision;
- source-state root digest;
- capability evidence paths and file digests;
- current capability-profiler policy.

A partial profile is not authoritative for model assignment and cannot produce a suite.

## Case structure

Each workload profile produces one case. A case contains:

- workload identity, kind, digest, trust role, and specialization profile;
- a versioned template identity;
- fixture policy and explicit remote eligibility;
- controlled capability, module, and evidence references;
- controlled technology, framework, database, testing, and quality references;
- required output section identifiers;
- benchmark dimensions and evaluation traits;
- quality, reliability, and latency weights;
- a deterministic case digest.

The initial score contract assigns 80 percent to quality, 10 percent to response reliability, and 10 percent to latency. A later benchmark runner records raw dimension results as well as the weighted total.

## Fixture policies

- `synthetic-only`: the runner must generate an isolated synthetic fixture.
- `sanitized-derived`: the runner may use only the controlled, source-content-free profile descriptor unless a separately approved fixture exists.
- `local-only`: the case cannot be sent to a remote provider. Database analysis uses this policy by default.

Remote eligibility is a data-handling classification only. It does not approve a provider call. Every remote run still requires its own session-bound provider approval.

## Persistence and staleness

Suites are derived records under `.krcn/projects/<project-id>/derived/model-benchmark-suites/`. The write uses an exact plan but does not require user-data approval.

A suite becomes stale when the project profile, source digest, workload digest, builder policy, template policy, or case contract changes. Rebuilding unchanged input is a no-op. List operations report `current` or `stale` explicitly.

## Safety invariants

- Source content is never persisted in the suite.
- Prompt content is never persisted in the suite.
- Secret values and absolute paths are prohibited.
- Building and listing perform no remote call.
- A suite grants no model, provider, project, database, or mutation authority.
- Case context overflow fails closed instead of being silently truncated.
- Case and suite digests detect persisted record tampering.

## CLI surface

```text
krcn model benchmark-suite <project-id>
krcn model benchmark-suite <project-id> --apply --expected-plan <plan-id>
krcn model benchmark-list
krcn model benchmark-list --project <project-id>
```

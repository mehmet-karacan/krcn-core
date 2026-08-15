# Execution Governance

## Purpose

Execution governance keeps an objective, its governing policy, unresolved
knowledge, evidence, and environment transitions independently verifiable. It
does not add a deployment engine or a second source of authority.

The canonical, transport-neutral contract is implemented in
`src/krcn_core/execution_governance.py`. CLI, SDK, MCP, client, scheduler, and
future adapters must preserve the same records and fail-closed checks.

## Immutable governance plan

A governance plan binds the following values by SHA-256 identity:

- project, task, and existing task-plan identities;
- the exact execution-governance policy digest;
- an objective logical reference and objective content digest;
- logical constraint references; and
- the creation timestamp.

The record contains no objective body, prompt, output, secret, credential, or
physical source path. Changing the objective, policy, task plan, or constraints
invalidates the governance-plan digest. A governance plan explicitly grants no
authority.

## Known, unknown, assumption, and deviation register

Each register entry is immutable and contentless. It records:

- one of `known`, `unknown`, `assumption`, or `deviation`;
- a logical topic, owner, and related-work reference;
- statement and evidence digests;
- severity and an explicit disposition;
- record time and optional superseded-entry digest; and
- its own tamper-evident digest.

An updated conclusion is a new entry that supersedes an earlier digest. The
original record is not overwritten. Duplicate identities, missing superseded
records, records from another plan, or digest changes fail closed.

An active `unknown` or `deviation` with `high` or `critical` severity and an
`open` or `blocked` disposition prevents an environment transition. A later
resolved or mitigated record can supersede it. Unknowns are therefore visible
decision inputs instead of text silently discarded from context.

## Environment promotion gate

The only promotion sequence is:

```text
dev -> test -> pilot -> production
```

Every plan moves exactly one adjacent stage. Direct `dev -> pilot`,
`test -> production`, or `dev -> production` promotion is rejected. Each plan
binds source and target environment digests, artifact digest, test digest,
independent verifier evidence digest, rollback digest, the register snapshot,
and the exact worker and verifier execution identities.

The worker and verifier must have different steps, actors, assignments, and
execution identities while binding the same governed task and task plan.
Model or client selection never relaxes this rule.

If an external provider is required, its logical provider reference, approval
reference, and existing authorization digest must be supplied together. The
record does not call the provider and cannot manufacture provider approval.

## Exact mutation and approval

Every transition prepares an existing `MutationPlan` for a portable user-data
record under the project's local-data boundary. The plan is reversible and
requires verified dry-run evidence plus explicit approval for that exact plan.
Approval for another transition, target, or content digest is invalid.

Passing the gate returns a contentless authorization record with
`does_not_execute: true`. It does not change the environment, persist a record,
start an agent, call a provider, or confer implicit authority. A future adapter
may execute and persist only through the existing mutation, provider, task,
lease, ownership, and database boundaries.

Immediately before authorization, the observed source stage and environment
digest must still match the reviewed plan. A stale source fails closed. Replays
are idempotent only when the complete authorization record is identical; a
changed timestamp or payload is a different attempt and is rejected when
presented as the same replay.

## Rollback

Rollback is a separate adjacent transition and a separate exact mutation plan.
It requires:

- the original promotion plan;
- the gate-passed authorization for that exact promotion;
- proof that the observed environment still matches the promoted target;
- fresh test and independent-verifier evidence;
- the reviewed rollback artifact digest; and
- its own dry-run and user approval before any adapter can act.

Rollback cannot be inferred from a failed test and cannot bypass an approval
boundary. The contract creates the rollback plan but performs no automatic
rollback or environment write.

## Storage and integration boundary

This package intentionally registers no command, application route, repository,
scheduler, provider, or persistence handler. It writes no governance register
or transition record. An integration slice may add those adapters only after
reviewing their ownership and authority boundaries. It must preserve all
digests, the independent verifier, the adjacent-stage rule, provider binding,
staleness checks, exact MutationPlan, user approval, and no-implicit-authority
flags defined here.

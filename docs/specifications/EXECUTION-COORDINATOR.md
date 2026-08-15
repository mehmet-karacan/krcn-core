# Execution Coordinator

## Purpose

The Execution Coordinator is a thin composition facade over reviewed KRCN
services. It binds one user request, intent, project, Work Item, context,
delegation decision, TaskPlan, authorization, model decisions, DAG plan,
verification evidence, continuity snapshot, handoff, trace, and status under
one immutable correlation identity.

It does not parse domain policy, select storage, grant approval, authorize a
provider, execute a project step, or verify its own result. Those decisions
remain owned by their existing services.

The transport-neutral `execution.coordinate` application operation exposes
the same immutable preparation contract. It is read-only and does not dispatch
the plan by itself.

## Routes

Exact lookup, status, and general conversation use `coordinator-response`.
They schedule zero agent calls and cannot carry a TaskPlan, model assignment,
or DAG plan.

Meaningful matched project work uses `delegated-dag`. It requires an
authoritative Work Item, coordinator-only delegation, a ready TaskIntent, a
TaskPlan with a verifier, task authorization, model assignments, and an exact
generic DAG plan. An unavailable delegation channel produces a `blocked` root
plan and cannot carry executable assignments.

## Execution

The facade calls an injected generic DAG dispatcher and a continuity finalizer.
The DAG dispatcher retains its exact mutation authorization, lease, heartbeat,
fencing, resource lock, parallelism, and adapter contracts. The continuity
service retains its bounded snapshot and authority-free handoff rules.

Finalization accepts only a complete DAG result bound to the root plan. Every
step must have evidence, at least one verifier must be present, and verifier
execution identities must differ from worker identities. The snapshot must
cover every completed step and the handoff must bind the same snapshot.

## Authority boundary

The root plan, result, trace, status, snapshot, and handoff all grant no
authority. A root plan with approval triggers remains `awaiting-approval` until
the underlying exact plan receives its own valid approval envelope. The
coordinator never turns composition into implicit mutation or provider access.

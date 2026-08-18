# Durable work continuity

## Purpose

KRCN persists the execution position of a multi-step project task outside chat history. A work item may have many ordered or dependent steps. Every completed worker step produces a checkpoint and an updated handoff. A later client reconstructs the completed, current, and next steps from local records.

## Authority

The Work Graph JSON item remains authoritative for the project task lifecycle. The persisted task plan, orchestration state, events, checkpoints, and handoff are runtime records. They preserve execution continuity but do not grant project, provider, mutation, model, or database authority.

## Persistent records

Layout v2 uses these project-scoped locations:

```text
.krcn/projects/<project-id>/
  work/items/<work-item-id>.json
  runtime/orchestration-plans/<task-id>.json
  runtime/orchestration-states/<task-id>.json
  runtime/events/orchestration/<event-id>.json
  runtime/checkpoints/orchestration/<checkpoint-id>.json
  runtime/orchestration-handoffs/<handoff-id>.json
```

The plan record binds one exact task plan to one project and one Work Graph item. It contains step titles, dependencies, digests, and verification requirements. It explicitly carries `grants_authority: false`.

## Checkpoint behavior

- A worker step is complete only after its digest-bound checkpoint is stored.
- Completed step identifiers are monotonic and cannot be removed by a later transition.
- The event chain is append-only and digest-linked.
- A repeated identical worker request uses the existing idempotency record.
- A missing or mismatched plan, event, or checkpoint blocks resume.
- A failed or interrupted uncheckpointed step remains pending.

## Resume behavior

`project.resume` returns `work.active_progress` for active persisted plans. Each entry includes:

- the Work Graph item identity;
- total, completed, pending, and failed step counts;
- the current step;
- dependency-ready next steps;
- a digest-bound resume token;
- whether a fresh authorization is required.

A new client must use the persisted progress instead of inferring completion from chat. It may continue an existing authorized execution only through the reviewed orchestration service. When a prior session authorization cannot be reused, the client prepares a fresh exact continuation plan for the remaining steps and keeps the prior checkpoints and handoff as history.

When the reviewed orchestration reaches independently verified completion, the same client-neutral service may append the bound Work Graph completion attestation and close the active item without asking for the already granted authorization again. Repeating the exact verified finish is a no-op. Missing proof or a relevant target/dependency change fails closed; an unrelated Work Graph item does not invalidate the target-scoped closure.

## Portability

Runtime continuity is local and ignored by Git. Thin capsule exports exclude runtime. Ready exports exclude active task runtime so leases or unfinished execution authority cannot move between machines. A paused or completed handoff may be carried only through the reviewed portability workflow. Derived indexes are not authoritative continuity records.

## Client obligation

For a meaningful project task with multiple steps, clients must:

1. bind the plan to the matched project and authoritative Work Graph item;
2. persist the exact plan before execution;
3. execute only dependency-ready steps;
4. record a checkpoint and handoff after every worker step;
5. read `project.resume` before continuing after an interruption;
6. never replace prior checkpoints with a chat summary.

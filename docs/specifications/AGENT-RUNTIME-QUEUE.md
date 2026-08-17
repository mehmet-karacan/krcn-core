# Agent runtime queue contract

## Purpose

The project runtime queue coordinates workers, verifiers, and delegated agents without granting ownership through an AI session. Queue ownership is temporary, fenced, project scoped, and independent from authoritative Work Graph state.

## Atomic boundary

Each project uses one SQLite database:

```text
projects/<project-id>/runtime/queue/scheduler-v1.sqlite
```

Queue items, attempts, leases, resource locks, scheduler events, and projection jobs change inside `BEGIN IMMEDIATE` transactions. Independent JSON files are not used to coordinate competing workers.

The stable filename remains `scheduler-v1.sqlite` for portable location
compatibility. Its current internal database schema is version 2. Existing
schema version 1 databases are changed only through the explicit additive
`runtime.queue.migrate-v2` exact plan; status and planning do not silently
migrate a database.

## Exact plan

Every mutating runtime action has a state digest and exact plan:

- `runtime.queue.enqueue`
- `runtime.queue.migrate-v2`
- `runtime.queue.claim`
- `runtime.queue.heartbeat`
- `runtime.queue.bind-effect-claim`
- `runtime.queue.bind-effect-receipt`
- `runtime.queue.complete`
- `runtime.queue.fail`
- `runtime.queue.recover`
- `runtime.queue.reconcile`

Runtime actions do not mutate user data and do not require user-data approval. They still require a verified dry-run and exact plan. Work Graph updates remain separate user-data mutations with their normal approval gate.

## Lease and fencing

The worker supplies an opaque owner token. Only its SHA-256 digest is stored. Every successful claim increments the queue item's fencing token. Heartbeat, completion, failure, lock release, and recovery evidence must match the current lease, owner digest, and fencing token.

An expired or superseded worker cannot publish a result. A new lease always has a higher fencing token.

## Effect ledger binding

A non-read queue item may opt into the version 2 ledger boundary by carrying a
pre-execution Validation Gate ID. Such an item cannot complete until a durable
Effect Claim and a completed terminal Effect Receipt are bound to its current
queue, attempt, lease, and fencing token. The bind actions re-read the
project-scoped durable Effect Ledger; caller-supplied IDs alone are not proof.

Version 1 rows migrate with `ledger_required=0`. This preserves old queue
history without retroactively inventing a gate or receipt. New governed
workers use the version 2 binding explicitly.

New non-read enqueue requests carry the complete Validation Gate payload, not
only its digest. A governed claim returns `handler_execution_allowed=false`.
Only after the matching durable claim is bound under the current lease/fence
does the queue return `handler_execution_allowed=true`.

The v1-to-v2 migration records a forward-only journal row with the pre-state
digest in the same SQLite transaction as the additive columns and metadata
revision. No destructive downgrade is attempted.

## Retry and recovery

- A read-only attempt can be replayed after expiry when retry capacity remains.
- An interrupted write, execute, or network attempt becomes `recovery-required` unless a stronger adapter-specific proof exists.
- Maximum attempts move the item to `blocked`.
- Completed checkpoints are represented by terminal queue state and are not executed again under the same idempotency key.
- Recovery never bypasses a user-data or remote-provider approval.

## Resource locks

Locks use portable logical references:

- `project:<project-id>`
- `task:<project-id>:<work-item-id>`
- `path:<project-id>:<relative-posix-path>`

Absolute paths, backslashes, and parent traversal are rejected. A project lock conflicts with every task and path lock in that project. Parent and child path locks conflict. Different project queue databases do not conflict.

## Delegation and verification

An agent or subagent is a worker or verifier role, not a new trust class. Verifier queue items may read or execute verification tools, but may not write or use the network. Project-scoped orchestration must identify both `project_id` and `work_item_id`, and its state, event, checkpoint, and handoff records are placed in the matching project capsule.

## Completion reconciliation

Runtime completion creates one idempotent projection job. The job cannot mark itself complete while the authoritative Work Graph item remains active. After the Work Graph is completed with evidence and its projection is current, `runtime.queue.reconcile` closes the projection job.

## Portability

Queue databases, leases, locks, active attempts, and nonterminal orchestration history are excluded from `thin`, `ready`, and whole-home portable backups. Completed orchestration history may be included in `ready` mode. Import never restores active worker ownership.

# Execution Observability

## Purpose

KRCN domain services retain their own internal state machines. This boundary
adds one correlation trace and one user-facing status projection above those
services. It does not replace Work Graph state, queue state, orchestration
events, research state, verification evidence, or derived artifact manifests.

Both records are operational projections. Neither record grants execution,
mutation, provider, database, approval, or lease authority.

## ExecutionTrace

`schemas/execution-trace.schema.json` connects one request to the reviewed
metadata produced across the execution lifecycle:

- correlation, request, client, project, and Work Item identities;
- intent, context, plan, evidence, and trace digests;
- an optional adaptive route decision ID used only for shadow correlation;
- delegation mode, model assignment IDs, queue IDs, and agent execution IDs;
- verification identity and canonical status;
- start, end, and derived duration;
- input, output, and cache token counts;
- optional estimated cost, retry count, cache hit, and failure code.

The trace stores identifiers and aggregate metrics only. It never stores the
raw request, prompt, model output, source content, secret, or physical path.
Cost is explicitly an estimate expressed as integer microunits and an ISO-style
three-letter currency code. A missing cost remains `null` rather than being
invented.

The trace digest covers every public field except itself. A trace with unknown
fields, invalid aggregate totals, reversed timestamps, or modified evidence is
rejected.

Phase 23 traces may include `route_decision_id`. Older version 1 traces that do
not contain this field remain readable and are normalized to a null route
binding. A route decision never changes execution and never supplies authority.

## StatusProjection

`schemas/status-projection.schema.json` exposes one of the following canonical
states:

- `preparing`
- `awaiting-approval`
- `queued`
- `running`
- `partially-completed`
- `awaiting-verification`
- `blocked`
- `degraded`
- `cancelled`
- `recovery-required`
- `completed`
- `derived-stale`
- `failed`

Internal Work Graph, queue, orchestration, research, verification, and derived
artifact statuses are mapped through one explicit table. Unknown internal states
fail closed. The user projection contains a safe summary, safe next action, and
reason codes. It does not expose the raw internal status map; it includes a
digest of that map for audit correlation.

Failure, cancellation, blocking, and recovery states take precedence over
progress states. Verification waiting takes precedence over running. Derived
staleness is visible even when the authoritative work completed. A degraded
execution is explicit without weakening any authority or verification gate.

## Composition boundary

`src/krcn_core/execution_observability.py` defines strict builders and parsers.
Domain services continue to own their internal status. The later Execution
Coordinator will collect those states, build the canonical projections, and
publish them through the shared application contract.

This package deliberately does not edit every domain service or add another
event store. Application and CLI clients must eventually render
`StatusProjection` rather than independently interpreting domain states, while
automation continues to receive the stable structured record.

## Safety invariants

- Trace and projection schemas are strict and digest-bound.
- Both records assert `grants_authority: false`.
- Trace records assert that raw payload and physical paths are absent.
- Unknown statuses, unknown fields, invalid metrics, and digest drift fail
  closed.
- Exact authoritative domain records override every projection.
- A projection can report an approval requirement but can never satisfy it.

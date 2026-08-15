# Runtime queue backend suitability

## Purpose

KRCN Core measures the current project-scoped SQLite runtime queue before it
adopts an external queue service. The measurement is a product development
decision input. It is not runtime state, execution authority, or permission to
install a service.

## Reference workloads

The small profile uses one project, one worker, and 100 queue items. The medium
profile uses eight independent project queues, four worker processes, and 400
items in total. This preserves the actual project-scoped storage boundary.

The benchmark records enqueue p95, claim p50 and p95, total throughput,
optimistic state retries, database bytes, lease recovery, stale fencing
rejection, integrity, and backup restore evidence.

## Candidate boundary

SQLite is the only measured V1 backend. Redis Streams, NATS JetStream, and a
PostgreSQL queue are capability candidates only. KRCN does not install, probe,
contact, import, or configure those services during this measurement. A
candidate marked `not-run` has no performance claim.

An external backend remains deferred until one of the versioned migration
triggers is observed and a separate exact adoption plan is approved. Candidate
selection never grants network, provider, secret, deployment, or migration
authority.

## Reproducibility

`tools/benchmark_runtime_queue.py` creates synthetic temporary queues and
removes them after measurement. It stores no project source, user data,
credential, physical path, or provider response. The recorded baseline binds
the measured runtime module and scheduler policy by digest.

The benchmark harness is not a production backend adapter. Production queue
semantics remain defined by `AGENT-RUNTIME-QUEUE.md` and the SQLite
implementation until a later reviewed decision changes them.

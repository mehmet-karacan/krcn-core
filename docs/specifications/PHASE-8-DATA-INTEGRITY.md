# Phase 8 data-integrity boundary

## Deployment state

Installation inspection recognizes only the statuses defined by the deployment journal state machine. `completed` and `rolled-back` are terminal. Every other valid state, including `failed`, is reported as interrupted and requiring recovery. Unknown states fail closed instead of being silently ignored.

## Record concurrency

Atomic file replacement protects readers from partial JSON, but it does not serialize competing writers by itself. Every local record apply operation therefore acquires a cross-process advisory lock for the logical record, rechecks the planned revision while holding that lock, writes atomically, and verifies the stored revision before releasing the lock.

Lock files contain no user content or authority. They are runtime coordination artifacts, remain outside Git, and are excluded from portable backup payloads.

## Memory freshness

Approved durable memory remains subordinate to current authoritative sources. Context construction compares the supporting source revision and digest of each memory record with the current authoritative catalog. A mismatch or missing current source makes the memory unavailable as stale. Stale memory is never silently included in context, and no lifecycle mutation is performed merely to compute freshness.

## Recovery

Corrupt backups, nonempty restore targets, interrupted migration, and failed rollback states are visible failure conditions. Recovery never deletes the preserved source home. A project-home migration retains its completed backup even if the target restore is interrupted and rolls back any local Git exclusion that was applied only for the failed target.

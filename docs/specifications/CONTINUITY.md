# Continuity Records

## Purpose

KRCN Core preserves authoritative project work in Work Graph records and
orchestration state. Continuity records are bounded, client-neutral projections
that let a new model, client, or session find the current verified position
without loading the complete history first.

Continuity records never replace authoritative state and never grant execution,
mutation, provider, database, lease, or approval authority.

## Record layers

### ContinuitySnapshot

`schemas/continuity-snapshot.schema.json` defines the first-read projection for
one project work item. The record includes the current goal and status, the
current step, bounded result sections, authoritative revision references, and
the next safe actions.

The default soft limit is 24 KiB and the hard limit is 32 KiB. When the soft
limit is exceeded, older low-priority entries are removed from the projection
and represented by `omitted_count`. Authoritative records remain unchanged.
The current identity, goal, status, current step, and next safe actions are not
silently removed. A record that still exceeds the hard limit is rejected.

A snapshot is stale and must be rejected or rebuilt when its Work Item revision,
orchestration state digest, or source revision contradicts the authoritative
records. Snapshot content cannot claim completed steps absent from the
authoritative execution state.

### WorkJournalEvent

`schemas/work-journal-event.schema.json` defines one meaningful append-only
operational event. Each event contains its own digest and the previous event
digest. The chain detects replacement, removal, insertion, reordering, mixed
Work Item identities, and time regression.

The journal stores results and operational evidence, not private reasoning. It
records completed or failed steps, observed errors, verified root causes,
rejected approaches, decisions, produced artifacts, verification outcomes, and
actor or source revision changes.

### FinalizedHandoff

`schemas/finalized-handoff.schema.json` defines the portable, authority-free
handoff derived from a verified snapshot. It contains the goal, completed and
pending work, decisions, risks, first reads, and the next safe action.

A finalized handoff never contains an authorization identifier, resume token,
owner token, active lease, secret, or machine-specific path. A new session must
obtain fresh authorization whenever the handoff says it is required. Reading a
handoff is never sufficient authority to resume execution.

## Persistence and composition boundary

The authoritative Work Graph, orchestration state, checkpoint, and event stores
remain unchanged. `src/krcn_core/continuity.py` builds, parses, and verifies the
three continuity projections. This package does not add another source of truth
or a separate workflow engine.

Application persistence and the later Execution Coordinator must write these
records through the existing ownership and mutation gates. A best-effort client
compaction hook may refresh a snapshot, but the durable guarantee remains the
checkpoint written after every meaningful worker step.

## Safety invariants

- Records use strict schemas and digest-bound identity.
- Unknown fields, credentials, and physical machine paths are rejected.
- Snapshot and handoff records assert `grants_authority: false`.
- A finalized handoff also asserts `carries_active_lease: false`.
- The journal is append-only and digest-linked.
- Semantic retrieval may locate old detail but never override exact authoritative
  state.
- Capsule portability may include a finalized handoff, but never an active lease
  or local execution token.

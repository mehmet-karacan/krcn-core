# Phase 4 context, knowledge, and memory boundary

## Baseline

Phase 4 starts from the completed `.ai/phase-3-baseline.json`. The ownership, policy, provider, adapter, mutation, local-store, and safe-merge gates remain authoritative. Phase 4 may extend these gates but may not create a bypass.

## Information classes

KRCN Core distinguishes six information classes:

1. `authoritative-source` identifies a canonical source at an exact revision.
2. `knowledge` stores curated, evidence-linked information derived from one or more sources.
3. `memory` stores approved durable information intended for later reuse.
4. `state` records resumable work in progress and is not durable truth.
5. `history` records prior decisions, operations, and verification evidence without claiming current validity.
6. `derived` contains rebuildable indexes, embeddings, summaries, and caches.

Information class and ownership class are separate dimensions. A classification never grants mutation authority.

## Authority and conflict rules

- A current authoritative source outranks knowledge, memory, state, history, and derived representations of the same fact.
- An explicit active user policy remains authoritative for enforcement and cannot be weakened by memory or retrieval output.
- Approved memory may guide future work but cannot silently override a current source, decision, or policy.
- Unapproved inference and conversation summary are candidates only.
- Contradictory evidence is surfaced as a conflict. The engine does not merge conflicting claims into an invented fact.

## Revision and staleness

Every retrievable record binds to a logical identity, revision, content digest, provenance, and evidence references. When a source revision changes, dependent knowledge, memory, and derived records become stale until revalidated or rebuilt. Stale memory is excluded from context through the same evidence comparison used for knowledge. Historical evidence stays immutable and is not relabeled as current truth.

Source discovery and rescan are explicit local operations, not a background filesystem watcher. A source change becomes visible to revision-based staleness checks after a user or client runs the read-only comparison and approved rescan flow.

## Retrieval order

The retrieval pipeline is layered:

1. exact identity and exact text retrieval;
2. dependency and relationship expansion;
3. semantic retrieval when allowed and useful;
4. deterministic ranking, deduplication, and budget allocation;
5. evidence-complete context package construction.

Exact and dependency retrieval must work offline. Remote semantic retrieval requires provider disclosure and exact session approval through the existing provider gate.

## Context package guarantees

A context package is a bounded projection, not a new source of truth. Every included item identifies its source, revision, digest, information class, ownership, selection reason, and truncation state. The builder must fail closed when required evidence is missing, a secret boundary is crossed, or mandatory context cannot fit the declared budget.

## Memory Gate

Durable memory follows a proposal and approval workflow. A candidate includes its type, intended scope, provenance, supporting evidence, conflicts, sensitivity, and retention purpose. Persistence, supersession, revocation, and policy promotion are separate mutations with separate authorization.

The system never persists the following automatically:

- raw conversation summaries;
- inferred user preferences;
- credentials or secret values;
- unverified claims;
- content that conflicts with a current authoritative source;
- policy changes inferred from behavior.

## Data and privacy boundary

Local source content remains in its authorized source by default. Retrieval may read content only within the source binding and adapter capabilities granted for the request. Public results expose logical references and evidence, not machine-specific paths, credentials, or secret values. Tests use synthetic local fixtures and no implicit network access.

## Client parity

CLI, SDK, MCP, plugins, Codex, Claude, and future clients invoke the same application service. Client adapters may translate natural language into typed requests but cannot reinterpret information authority, retrieval budgets, Memory Gate states, provider approval, or policy precedence.

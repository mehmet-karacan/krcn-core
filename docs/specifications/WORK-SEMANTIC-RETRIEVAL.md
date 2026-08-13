# Work Semantic Retrieval

## Purpose

KRCN keeps authoritative work state in WorkItem v1 records and uses
`work-graph-v1.sqlite` for exact, full-text, and relationship retrieval. The
semantic projection is separate and rebuildable:

```text
.krcn/projects/<project-id>/derived/retrieval/work-semantic-v1.sqlite
```

The semantic database never becomes an authoritative source. A stale or
invalid projection cannot be used for semantic search.

## Safe document boundary

The semantic document is derived only from these validated WorkItem fields:

- Work item identity, project identity, type, and status
- Title and description
- Acceptance criteria
- Relation type and target identity
- Human-readable evidence labels

Evidence references, evidence digests, provenance, source documents, absolute
paths, credentials, and secret values are not included. Path and secret
patterns in otherwise permitted text are redacted before vector generation.
The canonical document is used in memory and is not persisted in the semantic
database.

## Offline embedding profile

Version 1 uses the pinned `deterministic-hashing` profile with 192 dimensions.
It performs no provider discovery and makes no network call. Remote embeddings
are outside this contract and this module grants no provider authority.

The stored identity includes:

- Project identity
- Work Graph digest
- Retrieval policy digest
- Embedding profile identity
- Vector dimensions and count
- Work item and canonical document digests
- Complete semantic index digest

Changing any pinned identity makes the index stale and requires a rebuild.

## Incremental and atomic rebuild

An unchanged item is reused only when its WorkItem digest, canonical document
digest, embedding profile, and dimensions still match. Changed items are
reprocessed and removed items disappear from the new projection. Apply checks
the authoritative graph again, creates a temporary SQLite database, verifies
its integrity and identity, and replaces the target atomically.

## Retrieval precedence

Hybrid work retrieval uses strict evidence tiers:

1. Exact work item or external numeric identity
2. Work Graph full-text and lexical match
3. Work Graph relationship traversal
4. Semantic vector similarity

A lower tier cannot outrank a higher tier. Results expose each score and the
selected rank tier. Exact and lexical search remain available when a semantic
index has not been created. If a semantic index exists but is stale or invalid,
retrieval fails closed instead of silently returning outdated semantic results.

## Current API boundary

The core module provides these functions:

```text
prepare_work_semantic_index(...)
apply_work_semantic_index(...)
work_semantic_index_summary(...)
semantic_work_scores(...)
search_work(...)
```

Application service and CLI operations intentionally remain outside this
implementation slice. They must preserve exact-plan authorization for index
writes and project-scoped retrieval when added.

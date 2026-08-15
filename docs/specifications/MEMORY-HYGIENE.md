# Memory Hygiene and Context Effectiveness

## Purpose

Memory hygiene is a read-only analysis over reviewed metadata. It identifies
stale, conflicting, duplicate, unused, and retention-review candidates without
deleting, merging, superseding, revoking, or rewriting any authoritative
memory.

The simplest existing memory layer remains authoritative. Hygiene is an
optional overlay and does not introduce a graph database, another memory store,
or a new source of truth.

## Temporal and usage overlay

`schemas/memory-metadata-overlay.schema.json` adds optional metadata without
changing `information-record.schema.json` or the Memory Gate schemas:

- `valid_from` and `valid_until`;
- `last_used_at` and `usage_count`;
- `retention_review_at`;
- semantic digest and explicit conflict references.
- reviewer logical identity and review digest.

Missing optional timestamps remain `null`; they are never invented. A report
uses an explicit UTC `as_of` value, making classification deterministic and
testable. Expired validity, age, usage, conflict, and retention signals remain
separate categories. An overlay without reviewed-by identity and review digest
is rejected.

## Read-only hygiene report

`build_memory_hygiene_report` accepts reviewed metadata and emits
`schemas/memory-hygiene-report.schema.json`. The report includes only
identifiers, digests, classifications, duplicate groups, context measurements,
and authority-free suggestions.

The report never automatically deletes or merges records. It never treats a
derived projection as authoritative. Re-running with identical inputs and
policy produces the same digest.

For duplicates, the lexicographically first current memory identity becomes the
deterministic canonical suggestion. The other records are preserved and may be
suggested for supersession. Stale or retention-review records may be suggested
for revocation. Conflict-only and unused-only findings remain visible but do not
automatically create a lifecycle suggestion.

## Existing Memory Gate composition

Hygiene suggestions assert:

```text
requires_memory_gate = true
grants_authority = false
```

`prepare_reviewed_memory_action` accepts a suggestion only after a separately
approved existing `MemoryAction` exactly matches its action, memory identity,
revision, content digest, and replacement reference. It then calls the existing
`prepare_memory_lifecycle` boundary. The caller must still authorize and apply
that returned exact mutation plan through the existing Memory Gate.

Thus report generation, human review, exact planning, mutation authorization,
and apply remain separate operations.

## Research evidence dedupe

`schemas/research-evidence-metadata.schema.json` stores a canonical logical
source reference and a content digest without source content. Evidence records
sharing the exact content digest are grouped. Each group has one canonical
evidence weight; duplicates receive `duplicate-of` suggestions and zero
additional weight. The earliest `observed_at` record is canonical, with the
evidence ID as deterministic tie breaker.

Canonical source equality alone never proves duplication. When one source is
observed with different content digests, the report emits a time-ordered
`source-version-conflict` group. Every distinct content version retains evidence
weight one; no version is silently superseded or treated as corroboration of
another.

Duplicates are not deleted. This preserves provenance while preventing two
copies of the same video, paper, or report from being mistaken for independent
corroboration.

## Context effectiveness

`schemas/context-effectiveness.schema.json` measures:

- recall of required evidence;
- selected and actually used bytes;
- selected and actually used tokens;
- stale and duplicate selection rates;
- omitted-required-evidence rate;
- downstream verified success;
- compaction rehydration success.

All ratios use integer basis points. `config/memory-hygiene-policy.json` defines
the thresholds. The result and every derived metric are digest-bound. Context
quality can therefore be compared before adding a more complex retrieval or
graph layer.

## Safety invariants

- Inputs and outputs contain metadata, never memory/source content.
- Absolute paths, credential-like references, unknown fields, inconsistent
  counters, and tampered digests fail closed.
- Reports perform no filesystem or store mutation.
- No report or suggestion grants authority.
- Invalidation is proposed without discarding history.
- Existing authoritative memory and Memory Gate contracts remain unchanged.

## Python API

- `load_memory_hygiene_policy`
- `build_memory_metadata_overlay` / `parse_memory_metadata_overlay`
- `build_research_evidence_metadata` /
  `parse_research_evidence_metadata`
- `group_research_evidence_duplicates`
- `group_research_evidence_versions`
- `build_context_effectiveness` / `parse_context_effectiveness`
- `build_memory_hygiene_report` / `parse_memory_hygiene_report`
- `parse_hygiene_action_suggestion`
- `prepare_reviewed_memory_action`

Application scheduling, persistence, and CLI presentation are intentionally
outside this package.

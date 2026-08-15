# Phase 22 - Controlled Learning Governance

## Scope

This package adds two isolated governance boundaries without modifying the
existing application, CLI, registry, Memory Gate, repository context, current
work, capability registry, or storage layouts:

1. controlled skill candidate evaluation and approval planning;
2. read-only memory hygiene, research dedupe, and context effectiveness.

## Delivered

- Content-free and authority-free skill candidate records
- Source and repetition digest dedupe
- Project fixture, evaluation run, verifier, model, and environment binding
- Minimum trials, minimum passed trials, and score threshold
- Independent evaluator/verifier identity and model requirements
- Candidate self-promotion rejection
- Approval-required reversible registry Mutation Plan
- Explicit rollback and supersession metadata
- Active to deprecated/retired exact-plan transitions
- Optional temporal/usage memory metadata overlay
- Stale, conflict, duplicate, unused, retention, and not-yet-valid reporting
- Read-only, deterministic, digest-bound hygiene report
- Existing Memory Gate composition for reviewed supersede/revoke actions
- Canonical research source/content dedupe with a single evidence weight
- Required evidence recall, context use, stale/duplicate/omitted rates,
  downstream success, and compaction rehydration measurement
- Strict versioned configs and JSON schemas

## Explicit non-goals

- No skill code or content generation
- No registry write or registry configuration edit
- No automatic memory deletion, merge, supersession, or revocation
- No new graph, vector store, provider, model call, or external dependency
- No application or CLI registration in this isolated package
- No authority inferred from a report, evaluation, or lifecycle record

## Verification

Targeted tests cover digest tampering, secret/path rejection, deterministic
dedupe, the duplicate Avenox video 28/29 pair, independent verification,
insufficient trials, self-promotion, exact approval, lifecycle transitions,
temporal hygiene, zero automatic mutation, context measurements, and existing
Memory Gate composition.

Final foundation, JSON, diff-scope, and regression results are reported by the
implementing task and are not embedded as mutable counters in this document.

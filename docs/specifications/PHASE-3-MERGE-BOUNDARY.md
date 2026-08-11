# Phase 3 merge boundary

## Purpose

Phase 3 introduces the update engine that applies a newer KRCN Core release to an existing installation while preserving every registered project, document, integration, policy, secret reference, and unmanaged file.

## Entry baseline

Implementation starts only from the completed Phase 2 baseline in `.ai/phase-2-baseline.json`. Phase 2 application services remain authoritative for project inspection and non-destructive verification. The update engine must use the existing ownership, mutation, policy, provider, and adapter gates instead of creating parallel rules.

## First implementation slice

The first slice is read-only and contains:

1. installation inspection;
2. release manifest parsing;
3. compatibility evaluation;
4. ownership classification;
5. portable diff generation;
6. conflict reporting.

It must not copy, replace, migrate, rebuild, delete, or upload data.

## Apply prerequisites

No `merge into` apply behavior may be added until all of the following contracts exist:

- versioned release manifest and compatibility range;
- exact dry-run plan identity;
- recoverable backup plan;
- managed core file inventory and hashes;
- user-data preservation proof;
- versioned and repeatable migration contract;
- derived-data rebuild contract;
- post-merge verification plan for registered projects and integrations;
- rollback trigger and deployment record.

## Ownership rules

- `core` may change only when the target is present in the verified release manifest.
- `runtime` is preserved unless an explicit runtime migration is planned.
- `user-data` is preserved and never supplied by a core release.
- `derived` is preserved when compatible and otherwise rebuilt from authoritative sources.
- `secrets` are preserved locally and never read into plans, logs, or artifacts.
- `unmanaged` is preserved and reported as a conflict when it overlaps a managed target.

## Existing installation behavior

Inspection and diff operate against logical records and ownership references. Machine-specific source locators remain local and redacted. Registered projects and integrations are verification subjects after a future merge, not files to be copied into the release or rewritten by it.

## Client behavior

CLI, SDK, MCP, plugin, Codex, Claude, and future clients must invoke the same merge application service. A client may translate natural-language intent into a request, but it may not bypass dry-run, exact-plan, backup, approval, verification, or rollback requirements.

## Out of scope at entry

The Phase 3 entry does not authorize live installation mutation, real release application, user-data migration, credential access, remote provider use, database connection, or automatic rollback. Those effects require their own tested implementation slices and applicable user approval.

# Project capsule layout

## Status

This is the accepted Phase 11 layout v2 contract.

## Purpose

Project-specific KRCN records are grouped under `projects/<project-id>` so requests, defects, tasks, decisions, knowledge, runtime history, database metadata, and derived indexes do not share one flat namespace as the number of projects grows.

The layout changes KRCN-owned metadata placement. It does not change the external source no-copy boundary.

## Canonical layout

```text
<KRCN_HOME>/
  layout.json
  global/
    derived/
    knowledge/
    policies/
    runtime/
  projects/
    <project-id>/
      manifest.json
      project.json
      workspaces/
      bindings/
        source-bindings/
        integrations/
      integration/
      knowledge/
        authoritative-sources/
        records/
        relations/
      memory/
      policies/
      work/
      database/
      runtime/
      derived/
  local/
  locks/
  secrets/
```

`layout.json` identifies layout version 2. A project-local home created by the accepted project-home initialization contract also activates layout v2 through its validated `project-home.json` marker.

## Ownership

- Project records, work items, decisions, policies, knowledge, and portable database metadata are `user-data`.
- Rebuildable project and global indexes are `derived`.
- Queues, events, checkpoints, handoffs, and leases are `runtime`.
- Secret values remain `secrets` and never enter a project capsule archive.
- Machine-specific locators are local state. Export replaces a physical source locator with an `unbound` locator.

Active locks remain outside project capsules. A copied capsule must never imply that a process or worker from another machine still owns a task.

## Store compatibility

The local store reads both legacy layout v1 and layout v2. A home without a validated v2 marker continues to write the legacy layout. A v2 home writes project-scoped records into the inferred project capsule and unscoped records into `global`.

Record identity remains independent from physical placement. Duplicate copies of the same record identity in legacy and v2 locations fail closed.

## Derived placement

- The source-code index is project-specific and lives at `projects/<project-id>/derived/retrieval/source-code-v1.sqlite`.
- The current hybrid knowledge index is a cross-project projection and lives at `global/derived/retrieval/hybrid-v1.sqlite`.
- Derived data never replaces authoritative project, work, or database metadata records.

## Migration

Migration from layout v1 follows this order:

1. Inspect and hash every selected flat record and index.
2. Produce an exact plan with source and target references.
3. Require explicit approval for every backup, move, and generated manifest effect.
4. Write and verify a local rollback archive outside `KRCN_HOME`.
5. Materialize and verify target capsule files.
6. Remove only the exact backed-up flat files.
7. Publish `layout.json` last.
8. Reopen records through the layout v2 store and verify identities.
9. Automatically restore the flat layout if any apply or verification step fails.

The rollback archive is retained after success. Unclassified local files are preserved in place.

## Project capsule export

Two export modes are supported:

- `thin` includes durable project records and the minimum source identity evidence required for rebind, while excluding runtime and derived indexes.
- `ready` also includes verified derived data and portable runtime history, but excludes active queue ownership, leases, locks, machine locators, source content, and secret values.

Every exported source binding is transformed to an `unbound` locator. The archive records an external dependency and requires source rebind after import.

## Project capsule import

Import requires an existing layout v2 home and an absent target project capsule. Every archive entry is declared by the signed content identity inside the manifest, path checked, ownership checked, hash checked, and secret checked before planning.

Import never overwrites an existing project. It publishes the capsule only after staging verification. The imported project remains unavailable for source reads until an approved rebind verifies the selected external project directory.

## Git boundary

The complete KRCN home remains ignored by Git. Project capsule archives are local artifacts and are not added to the core repository. Source projects are never copied into KRCN Core or `KRCN_HOME`.

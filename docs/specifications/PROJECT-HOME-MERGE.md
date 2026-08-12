# Project-home merge contract

## Purpose

`portability.merge-project-home` merges durable records from one project-scoped KRCN home into an existing shared KRCN user home. It is intended for a target that already contains preserved content and therefore cannot use an empty-target migration.

The operation is client-neutral. CLI, SDK, MCP, plugins, Codex, Claude, OpenCode, and future clients submit the same application request and receive the same exact plan.

## Included records

The merge may add records under these user-data areas:

- `workspaces`
- `projects`
- `source-bindings`
- `integrations`
- `documents`
- `work-items`
- `decisions`
- `knowledge`
- `memory`
- `policies`

Project source files remain at the source binding locator and are never copied into KRCN storage.

## Excluded areas

The merge never copies:

- `project-home.json`
- runtime state, locks, events, or checkpoints
- derived state, indexes, embeddings, or caches
- `local-data`
- secret files or secret values
- target `staging` content

Derived state is rebuilt from the preserved source binding after the merge.

## Planning and conflict rules

The source home, target home, and backup directory must be separate absolute paths. The target may contain existing data. For every selected relative record path:

1. A missing target record is planned as a reversible user-data create.
2. An identical target record is preserved and counted without a write.
3. A different target record with the same path stops planning. The error reports record revision and payload hash metadata when available, but does not disclose physical source paths.

The public plan contains relative record paths only. It contains no physical home path or project source locator.

## Backup and apply order

Apply requires the exact dry-run plan identity and explicit user approval. Effects occur in this order:

1. Create and verify a secret-safe source-home backup.
2. Create and verify a secret-safe target-home backup.
3. Recheck both planned snapshots.
4. Add only the planned missing user-data records.
5. Verify every added record digest.

If a record write fails, records created by this operation are removed. Existing target content is never overwritten or deleted. The source home is never deleted or changed.

## Recovery

The source remains usable after the merge. The two verified archives provide an additional recovery boundary. Automatic restoration is intentionally separate from merge so recovery always has its own inspection, exact plan, and approval gate.

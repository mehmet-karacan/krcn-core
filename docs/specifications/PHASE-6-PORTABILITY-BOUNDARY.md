# Phase 6 portability boundary

## Purpose

Phase 6 makes KRCN-owned state portable without turning KRCN Core into a copy of the user's projects. The product core, the portable user home, external source directories, derived data, and secrets remain distinct ownership areas.

## Canonical layout

- The KRCN Core Git repository contains only versioned product code and managed defaults.
- A KRCN user home contains user-owned records, policies, knowledge, memory, runtime history, checkpoints, and rebuildable derived state.
- External project directories remain at their original locations and are represented only by local source bindings.
- Secret values remain in the local secret area or an external secret provider. Portable manifests may contain secret references but never secret values.

## Portability contract

Copying one KRCN user home and installing or pulling a compatible KRCN Core release must recover the user's KRCN context without copying project source files. A recovery verifies the portable manifest before applying changes.

External project directories are intentionally outside this guarantee. If a path changes on a new machine, KRCN requires an explicit rebind plan and verifies the selected directory before updating the local locator. It never searches for, copies, moves, uploads, or rewrites project content as part of backup, restore, migration, or rebind.

## No-copy source rule

- Source bindings store stable logical identities separately from physical locators.
- Local project discovery opens files for read-only inspection.
- Backup and restore traverse the KRCN user home only.
- Any path that resolves outside the user home is recorded as an external dependency, not archived content.
- A source directory may not be nested inside the KRCN user home.
- Rebinding changes only a user-owned locator record after exact-plan approval.

## Recovery outcome

After a portable restore, KRCN-owned records and execution history are available. Each external binding is reported as available, missing, changed, or requiring rebind. Missing project source never causes silent deletion of its project, policy, memory, or work records.

## Migration rule

Moving an existing repository-local `.krcn` directory to a canonical user home is a separate user-data mutation. KRCN must provide inspect, plan, backup, exact-plan approval, apply, verify, and rollback stages. It must not move live data automatically during installation or update.

## Compatibility and clients

Windows and macOS may choose different default physical user-home paths, but they use the same logical layout and manifest format. CLI, SDK, MCP, plugins, Codex, Claude, and other clients resolve the same user home and use the same application service gates.


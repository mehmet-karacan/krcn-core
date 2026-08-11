# Mutation gate

## Purpose

Every adapter that can create, update, delete, or move data must pass the same ownership-aware mutation gate before executing an effect.

## Required sequence

1. Express the target as a portable reference.
2. Resolve exactly one ownership class.
3. Create a deterministic mutation plan that includes the exact change digest.
4. Produce and verify a dry-run for that exact plan identifier.
5. Obtain user approval when the target is user-data, secrets, unmanaged data, or the operation deletes or moves content.
6. Confirm that the action is reversible.
7. Execute through the owning adapter.
8. Record non-sensitive verification and rollback evidence.

Approval for another plan, path, operation, or content digest is invalid. A command name or conversational assumption is not approval evidence.

## Fail-closed rules

- Absolute paths and parent traversal are not portable target references.
- A target that matches more than one ownership class is invalid.
- Direct secret mutation is prohibited; secret providers own that operation.
- Irreversible mutation is prohibited.
- Missing or mismatched dry-run evidence blocks execution.
- Required approval must identify the exact deterministic plan.

The Phase 1 gate authorizes plans but does not perform filesystem or external mutations. Adapters added in later phases must call this boundary immediately before their effect.

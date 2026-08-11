# Policy layers and preservation

## Purpose

This specification defines how KRCN Core combines product defaults, project rules, explicit user restrictions, and task-scoped instructions without losing user intent during an update.

## Ownership

- Versioned schemas and safe defaults are `core`.
- Approved user policy records under `.krcn/policies/**` are `user-data`.
- Policy evaluation state and temporary decisions are `runtime`.
- Credentials referenced by a policy remain `secrets`.

Core releases must not contain a user's policy values. They may contain schemas, validators, migration definitions, and safe default policies.

## Policy sources

From strongest to weakest:

1. Non-overridable platform safety controls.
2. Active user policy restrictions.
3. Explicit task instructions that further restrict behavior.
4. Project policy restrictions.
5. Core defaults.

A lower layer cannot weaken a restriction from a stronger layer. A deny result wins over allow. A persistent user restriction can be relaxed only through an explicit policy change that identifies the affected scope and receives user approval.

## Learning boundary

An agent may propose a policy after observing a repeated preference, but it must not silently promote an inference into an active user policy. Active records require one of these provenance kinds:

- `explicit-user`;
- `approved-memory`;
- `approved-import`.

Conversation summaries and derived memory are evidence candidates, not enforcement sources by themselves.

## Database example

If a user allows only read operations for a database integration, the user policy should allow `select` and deny mutation operations such as `insert`, `update`, `delete`, and `ddl`. The integration adapter must evaluate the effective policy before opening a mutation transaction or sending a statement.

Changing the core default or updating the integration adapter must not remove this restriction. Relaxation requires an explicit update to the user policy record.

## Update and merge behavior

Before applying a core update:

1. Discover user policy records without printing their sensitive scope values.
2. Validate them against the current or supported previous schema.
3. Preserve the original record and revision.
4. Produce a dry-run for any required migration.
5. Back up the record before migration.
6. Verify that the effective restrictions are equal to or stronger than before.
7. Roll back if validation or semantic comparison fails.

Core update conflicts must preserve the user record and stop for approval. Missing migration logic is not permission to replace a policy with a default.

## Adapter requirement

Every adapter that can mutate an external or local resource must declare its operations and evaluate the effective policy before execution. Read-only inspection may still require approval when a stronger user or platform rule says so.

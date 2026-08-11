# Database statement policy

## Purpose

This specification defines the fail-closed boundary between a KRCN Core database adapter and a user-managed database integration.

## Required order

Before sending text to a database, an adapter must:

1. Classify exactly one statement without opening a connection.
2. Resolve the integration source binding.
3. Load preserved policies for that integration.
4. Evaluate the classified operation.
5. Continue only when the effective decision is `allow`.
6. Record non-sensitive evidence after execution.

An adapter must not send the statement when parsing fails, the operation is unknown, no policy applies, approval is still required, or any matching policy denies it.

## Strict select behavior

A `select` permission permits only a single plain `SELECT` or a common table expression whose top-level operation is `SELECT`.

The following are not plain select operations:

- multiple statements;
- `SELECT INTO`;
- `SELECT ... FOR UPDATE`;
- data modification statements;
- DDL;
- transaction statements;
- session commands;
- procedural blocks and execution commands;
- unknown or malformed input.

Statement classification is only one layer. A production database adapter must also use the least-privileged credential and a read-only transaction or connection mode when the driver supports it.

## Legacy compatibility boundary

The reviewed legacy database index flow includes a non-select session command. That command is not allowed when an effective user policy permits only `select`. Read-only intent does not override a statement-level restriction.

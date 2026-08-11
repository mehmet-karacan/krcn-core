# Import boundary

## Purpose

This contract controls how existing local implementations and documents may inform KRCN Core without leaking machine-specific, user-owned, or confidential data into Git.

## Source bindings

Physical source locations are local configuration. They must never appear in committed files, release artifacts, logs, test fixtures, examples, or generated reports.

A source binding may contain a local path only when all of these conditions hold:

- the file is ignored by Git;
- the file is excluded from diagnostic bundles;
- the value is not printed by default;
- the binding has an explicit ownership class;
- deletion or replacement requires user approval.

## Import classes

### Portable core

May be imported after review:

- source code without local identifiers;
- schemas and generic policies;
- agent and skill contracts;
- platform-neutral launchers;
- hermetic tests and synthetic fixtures.

### Transform before import

Must be sanitized or redesigned first:

- code with implicit network access;
- code with hardcoded paths or installation names;
- monolithic code that mixes core and runtime ownership;
- tests that depend on a workstation, live project, optional driver, or external service;
- examples containing real project, account, network, or connection metadata.

### Reference only

May inform generalized requirements but must not be copied verbatim:

- local architecture notes;
- historical work records;
- project-specific skills and decisions;
- live operational behavior;
- user preferences and memory.

### Prohibited from Git

- user projects, documents, work items, requests, memory, and checkpoints;
- runtime events, locks, indexes, caches, and backups;
- database connection metadata and credentials;
- absolute paths, usernames, hostnames, IP addresses, email addresses, and organization-specific identifiers;
- private keys, tokens, passwords, local tool configuration, and secret references tied to a workstation;
- IDE state, bytecode, generated databases, and build output.

## Network rule

Import, indexing, validation, test, and migration operations are offline by default. A provider may receive local content only after explicit opt-in that identifies the provider, data categories, scope, and retention assumptions. Silent provider discovery is prohibited.

## Required gates

Before an imported file becomes tracked:

1. classify ownership;
2. scan for secrets and confidential metadata;
3. scan for machine-specific paths and identifiers;
4. remove implicit network behavior;
5. replace live data with synthetic fixtures;
6. run hermetic tests with network access blocked;
7. review the staged diff;
8. obtain user approval for the import batch.

## Failure behavior

If classification is ambiguous, the item remains outside Git. A failed or incomplete scan blocks import. No tool may treat a missing rule as permission.

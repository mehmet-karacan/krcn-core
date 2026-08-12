# Project-local KRCN home boundary

## Status

This is the accepted Phase 8 target contract. Until the Phase 8 resolver and initialization steps are implemented, the Phase 6 user-home resolver remains the executable behavior.

## Purpose

Project-scoped KRCN records should live close to the project without copying project sources or making local user data part of Git. The default proposed data root is `<project-root>/.krcn`.

## Resolution order

The shared core resolves a project home in this order:

1. An explicit exact `data_root` argument.
2. An exact `KRCN_HOME` environment value retained for compatibility.
3. A previously approved local project-home selection.
4. A non-mutating proposal for `<project-root>/.krcn`.

Resolution never creates a directory. A first-use client renders the proposal and allows the user to accept the default, choose another parent directory, or cancel. Choosing another parent produces `<selected-parent>/.krcn`. The application service returns typed choices and plans; transport-specific clients only render them.

## Initialization boundary

- Initialization is a user-data mutation.
- The exact physical target is shown before approval.
- An existing path is inspected before use and is never overwritten or adopted when its ownership is ambiguous.
- The approved plan becomes stale when the project root, target state, Git tracking state, or relevant policy changes.
- Subsequent runs reuse the approved selection without asking again.

## Git boundary

- Project-local `.krcn` content must not be tracked, staged, committed, pushed, or packaged as project source.
- The shared core verifies Git tracking and ignore state before initialization.
- A tracked project `.gitignore` is never edited silently.
- A client may propose a repository-local exclusion such as `.git/info/exclude`, but applying it remains an exact planned mutation.
- If any `.krcn` content is already tracked, initialization fails closed and reports remediation without deleting data.

## Source boundary

The project source remains read-only unless a separately authorized task grants a project-file mutation. The `.krcn` control directory is KRCN-owned user data nested under the project root and is excluded from discovery, source identity, indexing, and project-file mutation scope. KRCN never copies project files into this directory.

Project-owned local databases created specifically for KRCN may live under the local-data ownership area. External databases remain external integrations represented by logical bindings, policy references, and secret references only.

## Privacy and provider boundary

Creating or reading a project-local home does not grant network authority. Local data is not uploaded to Git, an AI provider, telemetry, or another remote service. Remote use still requires the provider gate and exact session approval. Secret values remain in an approved local or external secret provider and are excluded from normal backup artifacts.

## Recovery boundary

Git ignore is not backup. A clean clone does not restore project-local KRCN records. Portable backup and restore include approved KRCN-owned records while excluding project source content and secret values. A custom home outside the project is reported as an external local dependency when only the project directory is copied.

## Compatibility

Existing explicit and platform-default Phase 6 homes remain valid. No installation, pull, merge, project learning, or discovery command migrates them implicitly. Moving data to a project-local home requires inspect, backup, exact-plan approval, apply, verification, and rollback evidence.

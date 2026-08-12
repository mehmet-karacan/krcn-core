# Release quality gates

## Release decision

A KRCN Core release is eligible only when repository verification, the full hermetic test suite, doctor, offline wheel installation, portable backup and restore, external source no-copy, user-policy preservation, and rollback readiness all pass.

## Cross-platform CI

The versioned CI workflow runs on Windows and macOS with supported Python versions. It verifies repository content, executes the full suite, runs doctor, and builds the wheel. CI uses synthetic fixtures and never reads a developer's KRCN user home or external projects.

## Package content

The wheel must include the user-home resolver, source rebind, portable backup, portable restore, and repo-local migration modules. Offline installation must expose the same `OPERATIONS` set as the source tree.

## Rollback guarantees

- Core deployment uses the Phase 3 automatic rollback path after failed verification.
- Portable restore publishes no target user home until staging verification succeeds.
- Repo-local migration preserves the old `.krcn` source and never deletes it automatically.

## Release manifest boundary

Core release manifests still contain only managed core payload. User data, portable backups, source locators, external project files, runtime state, derived state, and secrets do not enter a core release bundle.

The required CI matrix covers Linux, Windows, and macOS. The full suite, repository scan, doctor, and offline wheel validation run without downloading product dependencies. A separate Linux job measures dependency-free line coverage with Python monitoring events and enforces the versioned 60 percent starting threshold in `.ai/coverage-baseline.json`.

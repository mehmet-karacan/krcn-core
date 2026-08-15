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

## Quality gate structure and baseline attestation

The workflow separates a fast Linux gate from the cross-platform release matrix. The fast gate runs repository verification, the full test suite, and doctor on the supported Python versions; the matrix adds Windows, macOS, offline wheel verification, and CLI installation checks.

Automatic triggers are held back while Actions usage is restricted, so both jobs currently run on demand. Enabling automatic verification is a trigger change only: restoring the commented `push` and `pull_request` entries makes the fast gate the required check for every pull request and development-branch push, while the matrix stays on demand and on release tags.

A versioned quality baseline is evidence only while it names the commit it was measured on. `.ai/coverage-baseline.json` and `.ai/cli-baseline.json` therefore carry a `source_commit` field. Doctor rejects a baseline without a usable measurement commit, and `tools/verify_baseline_attestation.py` reports which baselines were measured on an earlier commit. Ordinary development runs report that drift; a release run uses `--require-current` so that a stale baseline cannot be published as current evidence.

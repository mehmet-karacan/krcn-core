# KRCN Core machine contracts

This directory contains versioned, machine-readable defaults used by KRCN Core.

- `engines/` declares core engine responsibilities.
- `policies/` declares safe execution defaults.
- `registry/agents/` declares generic agent roles and capabilities.
- `repository-context.json` is the client-neutral repository context manifest.
- `current-work.json` points to the active plan, progress records, and next actions.
- `legacy-cli-inventory.json` records reviewed legacy behavior without importing source code.
- `cli-baseline.json` declares the sanitized and verified Phase 1 CLI surface.

User policy values belong under `.krcn/policies/**`, not in this directory. Runtime state, other user data, derived indexes, source bindings, and secrets must not be stored here.

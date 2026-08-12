# CLI reference

## Purpose

This document lists the KRCN Core command surface in one place so the README can stay a short product overview. The CLI is a thin transport layer only: plan, policy, approval, handler, checkpoint, and verification rules are enforced inside the shared application service, not in any client adapter. CLI, SDK, MCP, plugin, and AI clients all call the same service layer.

## Setup and health check

Install the package into the current Python environment without network access, then run the health check:

```bash
python -m pip install --no-index --no-deps --no-build-isolation .
krcn doctor
```

Run the same health check without installing:

```bash
python tools/krcn.py doctor
```

Resolve the active context machine-readably:

```bash
python tools/krcn.py context --format json
```

List the inspected legacy command contracts without running any operation:

```bash
python tools/krcn.py catalog
```

## Project learning

Introducing a new project only requires its directory. The service infers the project name and technical identifiers itself, inspects the source read-only, and shows an exact plan without copying files. On first use, the CLI first proposes `<source-directory>/.krcn` and writes nothing until the user selects a location. Location initialization and project learning are separate exact-plan mutations.

```bash
python tools/krcn.py project learn "<source-directory>"
python tools/krcn.py ask "<source-directory> projesini öğren"
python tools/krcn.py project list
python tools/krcn.py project inspect <project-id>
python tools/krcn.py project onboard --workspace-id <workspace-id> --project-id <project-id> --binding-id <binding-id> --name <project-name> --source <source-directory>
python tools/krcn.py project rescan <project-id>
```

Accept the proposed project-local home, inspect its exact plan, and then apply that same plan:

```bash
python tools/krcn.py project learn "<source-directory>" --home-choice use-default
python tools/krcn.py project learn "<source-directory>" --home-choice use-default --apply --expected-plan <plan-id> --approval-id <approval-id>
```

Choose another existing parent directory or cancel without writing state:

```bash
python tools/krcn.py project learn "<source-directory>" --home-choice choose-parent --home-parent "<parent-directory>"
python tools/krcn.py project learn "<source-directory>" --home-choice cancel
```

An explicit `--data-root` or `KRCN_HOME` continues to select an existing compatible home. Project-local `.krcn` content is excluded from source discovery and Git. Git ignore is not backup, so portable backup and restore remain required for machine recovery.

`onboard` and `rescan` also produce a plan only by default. Applying the plan requires the plan identity from the prior dry-run, and an explicit approval identity when the plan includes a user-data change.

## Knowledge, context, and memory

Revision-aware knowledge catalog and the Phase 4 shared services:

```bash
python tools/krcn.py knowledge catalog
python tools/krcn.py knowledge exact --request-file <application-arguments.json>
python tools/krcn.py knowledge dependencies --request-file <application-arguments.json>
python tools/krcn.py knowledge semantic --request-file <application-arguments.json>
python tools/krcn.py context-package build --request-file <application-arguments.json>
python tools/krcn.py memory propose --request-file <application-arguments.json>
python tools/krcn.py memory review --request-file <application-arguments.json>
python tools/krcn.py memory persist --request-file <application-arguments.json>
```

These commands define no product rules; they call the shared application service contract directly. Remote semantic search requires session approval and a scorer explicitly bound by the client. `memory persist` produces a plan only by default; a persistent write requires the same plan identity and a user approval that matches the review.

## Orchestrator (natural-language task flow)

```bash
python tools/krcn.py orchestrator intent --request-file <application-arguments.json>
python tools/krcn.py orchestrator plan --request-file <application-arguments.json>
python tools/krcn.py orchestrator authorize --request-file <application-arguments.json>
python tools/krcn.py orchestrator start --request-file <application-arguments.json> --apply --expected-plan <plan-id>
python tools/krcn.py orchestrator execute --request-file <application-arguments.json> --apply --expected-plan <plan-id>
python tools/krcn.py orchestrator verify --request-file <application-arguments.json> --apply --expected-plan <plan-id>
python tools/krcn.py orchestrator status --request-file <application-arguments.json>
python tools/krcn.py orchestrator resume --request-file <application-arguments.json>
```

Worker and verifier handlers must be registered explicitly before use; client selection alone grants no extra authority.

## Installation, release, and rollback

Inspect a local installation, view the trusted release diff, and produce an exact plan:

```bash
python tools/krcn.py installation inspect --installation <installation-directory>
python tools/krcn.py installation verify --installation <installation-directory>
python tools/krcn.py release diff --installation <installation-directory> --release <release-directory> --trusted-manifest-sha256 <sha256>
python tools/krcn.py release merge --installation <installation-directory> --release <release-directory> --trusted-manifest-sha256 <sha256>
```

`release merge` produces a plan only by default. Apply by re-running the same command with `--apply --expected-plan <plan-id>`. When the plan includes a user-data migration or delete, `--approval-id <approval-id>` is also required.

Rollback for a completed or interrupted deployment is planned first, then applied with the exact plan and required approval:

```bash
python tools/krcn.py deployment rollback <deployment-id> --installation <installation-directory>
```

## Verification tools

Validate repository ownership, provider, and import policies with no extra dependency:

```bash
python tools/verify_repository.py
```

Scan an import candidate against the current security policy:

```bash
python tools/verify_repository.py --source <source-directory>
```

The verification tool fails on secrets, machine-specific paths, sensitive connection details, blocked file types, and long-dash findings. It uses no network access.

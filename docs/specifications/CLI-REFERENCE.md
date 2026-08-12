# CLI reference

## Purpose

This document lists the KRCN Core command surface in one place so the README can stay a short product overview. The CLI is a thin transport layer only: plan, policy, approval, handler, checkpoint, and verification rules are enforced inside the shared application service, not in any client adapter. CLI, SDK, MCP, plugin, and AI clients all call the same service layer.

## Setup and health check

On Windows, inspect the one-time user installation plan, apply it, open a new terminal, and run the health check:

```powershell
py tools\install_cli.py --plan-only
py tools\install_cli.py
krcn doctor
```

The installer verifies and installs the wheel without network access, records the approved clone in user-level `KRCN_CORE_HOME`, and leaves `KRCN_HOME` unchanged. Rerun it after an approved Git update. See `docs/specifications/CLI-INSTALLATION.md` for the lifecycle and recovery contract.

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
python tools/krcn.py project integrate --source "<source-directory>" --scan-mode manual
python tools/krcn.py project integrate --project <project-id> --scan-mode automatic
python tools/krcn.py project index-code <project-id>
python tools/krcn.py project search-code <project-id> "<source-question>"
python tools/krcn.py project list
python tools/krcn.py project inspect <project-id>
python tools/krcn.py project current
python tools/krcn.py project resume --request "<user-request>"
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

Migrate an existing compatible KRCN home without deleting it, or restore its verified backup into a clean project clone:

```bash
python tools/krcn.py portability migrate-project-home --source-home "<existing-home>" --project "<project-directory>" --backup-output "<backup-file>" --home-choice use-default
python tools/krcn.py portability restore-project-home --input "<backup-file>" --project "<clean-project-directory>" --home-choice use-default
```

Both commands produce a dry-run plan first. Apply requires the exact returned plan identity and an explicit approval identity. A migration writes the backup before the target and never deletes the original home.

Merge selected records from a project-scoped home into an existing shared home without overwriting either side:

```bash
python tools/krcn.py portability merge-project-home --source-home "<project-home>" --target-home "<shared-home>" --backup-directory "<new-backup-directory>"
python tools/krcn.py portability merge-project-home --source-home "<project-home>" --target-home "<shared-home>" --backup-directory "<new-backup-directory>" --apply --expected-plan <plan-id> --approval-id <approval-id>
```

The source and target backups are written and verified before any target record is added. Existing target content is preserved. Derived state must be rebuilt with `project rescan` after the merge.

`onboard` and `rescan` also produce a plan only by default. Applying the plan requires the plan identity from the prior dry-run, and an explicit approval identity when the plan includes a user-data change.

`project current` resolves a registered project from the current directory. `project resume` adds the persisted source, information, and active-work summary. Use `--project <project-id-or-name>` for an explicit selection or `--request "<user-request>"` when the request names a project while the client is running elsewhere. Both commands are read-only and never disclose a physical source locator.

`project integrate` completes registration, discovery, evidence-bound knowledge, capability-profile, local knowledge-vector index, contentless source-code index, and verification stages. Manual mode always scans for an explicit integration request. Automatic mode scans after the versioned 24-hour freshness interval or when a required stage is missing. A fresh complete integration is a no-op. Any user-data mutation still requires the exact returned plan and an explicit approval id.

`project index-code` is the separate maintenance entrypoint for the same project source-code index. It is exact-plan controlled derived data. `project search-code` combines relative-path and symbol matching with local vectors. By default, selected chunks are hash-verified and read from the external project in place. Use `--metadata-only`, repeated `--language`, `--path-prefix`, and `--limit` to narrow the result. The index stores no source text or physical source root.

## AI client bootstrap

Inspect and install the user-level KRCN discovery block for Codex, Claude Code, and OpenCode:

```bash
krcn client bootstrap
krcn client bootstrap --apply --expected-plan <plan-id> --approval-id <approval-id>
```

The first command is read-only. Apply backs up every existing client instruction file into the active ignored KRCN local-data area, preserves content outside the managed KRCN markers, and rolls back already changed client files if a later write fails.

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
python tools/krcn.py orchestrator timeline --request-file <application-arguments.json>
python tools/krcn.py orchestrator resume --request-file <application-arguments.json>
```

Worker and verifier handlers must be registered explicitly before use; client selection alone grants no extra authority.

`status` includes the current resume summary and a readable event timeline. `timeline` returns only the digest-verified event sequence. Neither operation returns worker input, handler output, secret values, or physical source locations.

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

## Salt okunur yerel veritabanı entegrasyonu

`krcn integration select` komutu kayıtlı bir integration ve source binding üzerinden yalnız policy tarafından izin verilen `SELECT` sorgularını çalıştırır. `--integration-id`, `--binding-id` ve `--statement` zorunludur; `--maximum-rows` public yanıta alınmayacak sonuç satırları için üst sınırdır.

Bağlantı değeri komut satırına yazılmaz. Örneğin `secret://database/reporting` kaydı aktif proje evindeki `secrets/database/reporting.secret` dosyasına karşılık gelir. Dosya bir SQLite `file:` URI'si ve `mode=ro` parametresi taşımalıdır. Secret değeri, fiziksel veritabanı yolu ve sorgu satırları çıktıya yazılmaz.

## Yerel hibrit bilgi arama

`krcn knowledge index` önce yeniden üretilebilir SQLite indeks planını gösterir. `--apply --expected-plan <plan-id>` aynı planı `derived` alana uygular. Bu işlem kullanıcı verisini değiştirmez ve harici proje dosyalarını kopyalamaz.

`krcn knowledge hybrid --request-file <json>` exact, FTS, yerel vektör, dependency, authority ve availability sinyallerini ortak sıralamada çalıştırır. JSON dosyasındaki `query`, `schemas/hybrid-retrieval-query.schema.json` sözleşmesine uyar. Arama yapılmadan önce indeksin güncel katalog için oluşturulmuş olması gerekir.

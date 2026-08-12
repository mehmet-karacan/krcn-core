# User-level AI client bootstrap contract

## Purpose

KRCN installs one short global guidance block for Codex, Claude Code, and OpenCode so each client knows that the shared `krcn` command is available. Project directories do not need client-specific files merely to discover KRCN.

The managed targets follow each client's user-level instruction convention:

- Codex global `AGENTS.md`
- Claude Code global `CLAUDE.md`
- OpenCode global `AGENTS.md`

Physical target paths are local implementation details and never appear in public plans.

## Managed block

KRCN owns only the content between `KRCN-CORE:BEGIN` and `KRCN-CORE:END` markers. Existing content before and after that block is preserved byte for byte. A subsequent installation replaces only the managed block. Duplicate, partial, or malformed markers stop planning.

The guidance tells a client to:

1. Use `krcn project current` before project work.
2. After a match, use automatic `krcn project integrate` mode to check the 24-hour freshness window and missing stages. A current integration is a no-op; any mutation remains exact-plan and approval gated.
3. Use `krcn project resume` before answering a where-we-stopped question.
4. Use an explicit registered project selection when the user names another project.
5. Treat returned context as information rather than mutation authority.
6. Keep project source in place and preserve KRCN policy and approval gates.

Product rules remain in KRCN Core. Client files do not duplicate matching, policy, ownership, or orchestration logic.

## Exact plan and backup

`client.bootstrap` is a shared application service operation. A dry-run plan binds each target's original and rendered SHA-256 identity. Apply requires that exact plan and explicit user approval.

Before an existing client file is changed, its original bytes are stored under the active KRCN home's ignored local-data backup area. A matching prior backup is reused. A conflicting backup identity stops the operation. Secret-like existing content stops planning so it is never copied into KRCN backup storage.

## Apply and rollback

All target snapshots are rechecked before any backup or target write. Backups are written and verified before client instructions change. Target writes are atomic. Every managed marker and final byte sequence is verified.

If one target write fails, previously changed client files are restored to their original state. Backup files remain available for recovery. Reapplying an already current bootstrap is a no-op.

## Precedence note

Global guidance does not replace closer repository instructions. A client combines or prioritizes its project guidance according to its own documented behavior. KRCN's global block only provides discovery and safe routing; repository-specific rules remain authoritative within their scope.

# User-level AI client bootstrap contract

## Purpose

KRCN installs one short global guidance block for Codex, Claude Code, and OpenCode so each client knows that the shared `krcn` command is available. Project directories do not need client-specific files merely to discover KRCN.

The managed targets follow each client's user-level instruction convention:

- Codex global `AGENTS.md`
- Claude Code global `CLAUDE.md`
- OpenCode global `AGENTS.md`

Physical target paths are local implementation details and never appear in public plans.

## Managed block

KRCN owns only the content between `KRCN-CORE:BEGIN` and `KRCN-CORE:END` markers. If no managed block exists, the original file remains an exact byte prefix and the KRCN block is appended at the end. Existing content before and after a managed block is preserved byte for byte. A subsequent installation replaces only the managed block. Duplicate, partial, or malformed markers stop planning.

The guidance tells a client to:

1. Use `krcn project current` before project work.
2. After a match, use automatic `krcn project integrate` mode to check the 24-hour freshness window and missing stages. A current integration is a no-op; any mutation remains exact-plan and approval gated.
3. Use `krcn project resume` before answering a where-we-stopped question.
4. Use an explicit registered project selection when the user names another project.
5. Treat returned context as information rather than mutation authority.
6. Keep project source in place and preserve KRCN policy and approval gates.
7. Before meaningful work on a matched project, declare only the capabilities available in the current client session and request a `krcn client delegation` decision.
8. Keep the main agent coordinator-only when delegation is required. Source inspection, domain analysis, implementation, tests, and independent verification belong to delegated roles.
9. Prefer native parallel execution for independent work. Report sequential or isolated-role fallback as degraded execution. Stop when delegation is unavailable instead of silently performing project work in the main agent.
10. Resolve a model profile before delegation when the client supports model selection. A client that cannot select models keeps its current default. Embedding provider approval remains a separate gate.

Native attributed terminal text is a delegated result channel, but it does not
by itself mean structured-result support. Clients declare structured results only
when delegated payloads are independently machine-validatable against an explicit
result contract. Mode selection is client-neutral, and optional capabilities do
not block a genuine native parallel channel.
11. Keep client-generated operational artifacts out of `KRCN_CORE_HOME` and registered project sources. Supported project artifacts use `.krcn/projects/<project-id>/local-data/client-artifacts/`; `.krcn/global/local-data/client-artifacts/` is reserved for project-independent output. Without a reviewed write operation, the client returns the result and asks before creating a file.
12. Treat versioned core writes as authorized only by an explicit KRCN Core product-development request. Integration, audit, retrieval, and ordinary project work are not core mutation authority.

Product rules remain in KRCN Core. Client files do not duplicate matching, policy, ownership, or orchestration logic.

Capability and delegation decisions are read-only. They do not replace or satisfy an exact plan, user approval, provider approval, database policy, ownership rule, or mutation authorization.

The artifact rule separates product source from machine-local work output. `docs/`, `.ai/`, the repository root, and external project directories are not fallback output locations. The managed guidance cannot replace operating-system access control, so application operations and repository verification remain the enforcement boundary for writes performed through KRCN.

If the global command later becomes unavailable, the managed guidance preserves the pending user request and routes recovery through the validated core clone's installer plan. After explicit installation approval and verification, the client resumes the original request instead of asking the user to repeat it.

## Exact plan and backup

`client.bootstrap` is a shared application service operation. A dry-run plan binds each target's original and rendered SHA-256 identity. Apply requires that exact plan and explicit user approval.

Before an existing client file is changed, its original bytes are stored under the active KRCN home's ignored local-data backup area. A matching prior backup is reused. A conflicting backup identity stops the operation. Secret-like existing content stops planning so it is never copied into KRCN backup storage.

## Apply and rollback

All target snapshots are rechecked before any backup or target write. Backups are written and verified before client instructions change. Target writes are atomic. Every managed marker and final byte sequence is verified.

If one target write fails, previously changed client files are restored to their original state. Backup files remain available for recovery. Reapplying an already current bootstrap is a no-op.

## Precedence note

Global guidance does not replace closer repository instructions. A client combines or prioritizes its project guidance according to its own documented behavior. KRCN's global block only provides discovery and safe routing; repository-specific rules remain authoritative within their scope.

Project integration never writes `AGENTS.md`, `CLAUDE.md`, or another client instruction file in the external source tree. A future project-local bootstrap must remain a separate exact-plan operation and may replace only a KRCN managed block.

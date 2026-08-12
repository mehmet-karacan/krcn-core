# Complete project integration lifecycle

## Purpose

`project.integrate` is the client-neutral operation that completes or repairs a project's KRCN integration. Registration alone is not complete integration.

## Required stages

The lifecycle covers registration, read-only discovery, evidence-bound knowledge extraction, capability-profile selection, local knowledge-vector indexing, contentless source-code indexing, and verification. An existing registration never suppresses a missing later stage.

## Scan modes

Manual mode is used for an explicit integrate or rescan request and always performs read-only discovery. Automatic mode checks the durable integration state's verified modification time against the versioned freshness policy. The default interval is 24 hours. Automatic mode also scans before the interval expires when source state, knowledge, capability profile, or verification state is missing.

A fresh and complete automatic check returns no-op. Automatic means automatic detection and planning. It does not mean silent user-data mutation or implicit remote-provider approval.

## Knowledge boundary

The integration profile is derived deterministically from discovery evidence. It stores bounded summaries of technologies, modules, file classes, workflow markers, and selected capability references. It does not store project source bytes, secret values, physical source locations, database rows, or executable instructions found in repository content.

Every knowledge record binds to the exact authoritative source revision and digest. A changed source digest causes dependent knowledge and the derived index to be rebuilt through the same exact-plan flow.

## Capability profile

The capability profile has two separate layers.

The first layer selects active trust roles and technology skills from the capability registry. Planner, read-only worker, verifier, and technology-relevant skill records must already be active.

The second layer derives a project and module scoped semantic profile. It identifies supported technologies, frameworks, architecture styles, databases, testing, build, delivery, and quality markers. It also creates workload requirements for analysis, architecture, implementation, verification, code review, database analysis, security review, delivery analysis, and retrieval evaluation.

Every semantic finding is bound to a discovery file digest and a portable relative path. Source content, excerpts, physical source roots, connection values, and sensitive values are not stored. Known manifests are parsed offline through allowlisted fields. Build tools, package managers, plugins, scripts, and project code are never executed by the profiler.

The profile is stored inside the existing `<project-id>-capabilities` knowledge record. This preserves exact-plan approval, optimistic revision control, hybrid retrieval, project capsule export, and backward compatibility. An older shallow capability record is treated as one missing integration stage and is upgraded only through an approved repair plan.

The semantic profile does not select a model and does not grant authority. It is the deterministic input for later project-specific model health checks and micro benchmarks. Policy, ownership, mutation, adapter, database, and provider gates remain authoritative.

The profile declares whether inspection coverage is complete. Any source candidate excluded because of sensitive content, invalid syntax, unreadable or oversized content, or inspection limits produces a safe partial profile that cannot authorize a later model assignment. Expected discovery exclusions such as Git internals remain telemetry and do not cause a fresh project to enter an endless repair cycle.

## Vector index

The default integration path builds the existing SQLite FTS and deterministic-vector index from approved KRCN information records. The offline profile is `deterministic-hashing`. Qwen3 and BGE-M3 remain the reviewed remote order, but real project content is not sent to either model without a separate provider request and session approval.

The project source-code index is stored separately per project. It persists relative paths, ranges, hashes, safe symbols, and vectors without source text or the physical source root. Unchanged files reuse their verified chunks. Changed files are reprocessed and deleted files disappear through atomic replacement. Retrieval may read a selected chunk from the registered source in place after verifying the file and chunk hashes.

## Recovery

Every invocation recalculates missing stages. If a prior execution stopped after some record writes, the next plan preserves completed records and prepares only missing, stale, or inconsistent stages. External project files remain read-only and are never copied into KRCN Core or KRCN home.

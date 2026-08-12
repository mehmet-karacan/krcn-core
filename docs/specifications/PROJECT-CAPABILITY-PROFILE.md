# Project capability profile

## Purpose

The project capability profile describes what an integrated project needs before models or subagents are assigned. It keeps project understanding separate from model quality and execution authority.

## Trust roles and specialist workloads

Trust roles remain `read-only-worker-agent`, `worker-agent`, and `verifier-agent`. They define what an execution may do.

Specialist workloads define what kind of reasoning is needed. The initial workload set covers analysis, architecture design, implementation, verification, code review, database analysis, UI analysis, security review, delivery analysis, and embedding evaluation.

A workload profile never grants a trust role. A future model assignment must satisfy both the required workload quality and the independently authorized trust role.

## Evidence model

Every capability finding has at least one evidence reference. Evidence contains only:

- A portable relative path
- The exact discovery file digest
- A controlled marker identifier
- The evidence family and scope
- An optional deterministic line range

Evidence does not contain source excerpts, commands, URLs, host names, connection strings, physical paths, or sensitive values. The entire profile is deterministic for the same source snapshot and profiler policy.

## Safe inspection

The profiler reads only files present in the exact discovery result. It rejects symbolic links and source-root escapes, verifies the file size and SHA-256 digest, enforces an inspection size limit, and accepts UTF-8 text only.

Content is checked with the central sensitive-content detectors before marker extraction. A sensitive manifest or source file contributes no content marker. JSON, XML, and TOML manifests are parsed through allowlisted fields. Gradle and SQL use bounded offline marker recognition. Nothing from the project is executed.

Credential detectors are distinct from portability and contact-data detectors. Normal author metadata does not hide safe dependency identifiers, while tokens, private keys, credential assignments, and credential-bearing URIs cause the complete candidate file to be skipped. Evidence paths are checked separately and never contain a machine path or contact identifier.

Inspection has deterministic per-file, total-file, total-byte, and evidence budgets. A malformed, oversized, unreadable, or budget-excluded candidate becomes a counted limitation instead of blocking the complete project integration.

The profile reports `complete` or `partial-safe` coverage. A profile with a sensitive, oversized, unreadable, invalid, budget-excluded, or evidence-limit-excluded candidate is not authoritative for model assignment. Expected discovery exclusions such as `.git` remain visible as telemetry but do not by themselves downgrade capability coverage.

## Project and module scope

Successfully parsed production manifest directories establish module scopes. Nested evidence is assigned to its nearest parent manifest. This lets one repository contain, for example, a Spring backend and a React frontend without combining their evidence into one false module claim.

Framework and database names require direct or strong evidence. A plain `package.json` does not mean frontend, a plain `pom.xml` does not mean Spring, and a generic SQL file does not mean Oracle or PostgreSQL.

Example, fixture, and documentation manifests or delivery markers do not produce production capabilities. Test-scoped dependencies may establish test capability but never establish a production framework or backend. Specialist workloads are scoped only to modules that contain their trigger capabilities. Trust role and specialist profile identifiers remain separate fields.

## Lifecycle

The profile is stored as structured data inside the existing project capability knowledge record. The record remains user data and uses the existing exact-plan approval flow.

The profile is stale when its binding, source digest, profiler revision, policy digest, evidence digest, or internal references no longer match. A stale or legacy profile causes the existing `capability-profile` integration stage to be planned for repair. No repair is applied silently.

## Model qualification boundary

The profile prepares workload-specific benchmark requirements. It does not hold model credentials, health state, benchmark results, or model assignments. Those records belong to the later model qualification layers and must reference the exact project profile and workload digests.

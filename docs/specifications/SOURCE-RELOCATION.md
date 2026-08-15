# Source Relocation and Exact Rebind

## Purpose

KRCN separates a source location from source identity. A folder path can change
without changing the registered project, while a folder with the same name can
contain a different history. Path similarity never proves identity.

## Classifications

Every reviewed candidate has one of four classifications:

- `relocated-same-source`: logical identity, root digest, and file count match.
  Locator-only exact rebind is allowed.
- `same-project-new-revision`: reviewed history evidence proves a linear source
  revision. Project integration is required and derived indexes become stale.
- `diverged-clone`: reviewed history evidence proves a divergent history.
  Reconciliation is required and revisions must not share one current index.
- `unrelated-source`: logical identity or reviewed history does not match. A
  separate project registration is required.

A changed digest without reviewed relationship evidence fails closed. KRCN does
not infer Git ancestry from a directory name, remote label, or user statement.

## Locator-only rebind

`prepare_source_rebind` accepts only `relocated-same-source`. It rejects the
already active locator and produces an exact mutation plan that changes local
binding and source-state records only. The candidate path is never included in
the public plan.

Apply revalidates the candidate discovery, source identity, record revisions,
plan identifier, and per-record approvals. Registered source files remain
read-only and are never copied into KRCN user data.

## Index behavior

An exact rebind preserves the content digest and declares
`verify-current-manifest-and-reuse`. Binding revision remains part of index
freshness. The derived source index is rebuilt with verified reusable file
evidence, so no unchanged source file needs to be embedded again.

A linear new revision declares `mark-stale-and-rebuild`. A divergent clone uses
`separate-revision-index`. An unrelated source uses `create-separate-project`.
No classification grants mutation, provider, model, database, or execution
authority.

## Invariants

- Physical paths are local-only and absent from public assessments.
- Source content and credentials are absent from assessments and plans.
- Digest mismatch is never treated as a path move.
- Rebind approval applies only to the exact candidate and exact record plans.
- Classification is read-only and grants no authority.

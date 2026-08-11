# Update and merge contract

## Purpose

The update engine applies a newer KRCN Core release to an existing local installation without sending, deleting, or silently overwriting user-owned data.

## Proposed command model

```text
krcn inspect <installation>
krcn diff <release> into <installation>
krcn merge <release> into <installation> --dry-run
krcn merge <release> into <installation> --apply
krcn verify <installation>
krcn rollback <installation> <deployment-id>
```

Natural-language interfaces may translate user intent into these operations, but they must preserve the same safety contract.

## Ownership behavior

| Class | Merge behavior |
|---|---|
| core | Replace only when managed by the release manifest |
| runtime | Preserve and migrate only through an explicit runtime migration |
| user-data | Preserve; never include in a core release |
| derived | Preserve when compatible, otherwise rebuild from authoritative sources |
| secrets | Preserve locally; never read into release artifacts or logs |
| unmanaged | Preserve and report conflicts |

## Required merge sequence

1. Inspect the target installation.
2. Validate the release signature, manifest, and compatibility range.
3. Classify all affected paths by ownership.
4. Produce a dry-run plan and conflict report.
5. Create a recoverable backup of affected managed state.
6. Apply managed core changes.
7. Run versioned schema migrations.
8. Migrate or rebuild derived data when required.
9. Verify projects, documents, work items, and registered integrations.
10. Write a deployment record containing release, source commit, hashes, migrations, and verification results.
11. Roll back automatically when mandatory verification fails.

## Non-negotiable guarantees

- No local project or document content is uploaded by the update process.
- No user-owned file is deleted or overwritten because it differs from a release.
- No secret is committed, packaged, logged, or included in a diagnostic bundle.
- Repeating the same merge is idempotent.
- Interrupted merges are detectable and recoverable.
- A failed verification cannot be reported as a successful deployment.
- The active core release and schema versions are always queryable.

## Integration verification

Every registered integration must expose a non-destructive health check. After a merge, the verifier checks configuration compatibility, adapter availability, schema compatibility, credential reference presence, and read-only connectivity where safe. Secret values must not be displayed.

## Open design decisions

- Final CLI executable and command names.
- Release signing mechanism.
- Backup retention policy.
- Conflict policy for locally modified managed core files.
- Supported migration transaction boundaries.
- Exact location of runtime and user-data directories on each operating system.

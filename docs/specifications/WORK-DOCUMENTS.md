# Work Documents

## Purpose

Work Documents stores project request, defect, and task documents separately
from registered source code. The documents are user-owned data. Repository
sources and database rows are never copied into this area by this workflow.

## Canonical request and defect layout

Layout version 2 uses the external work identity as the only navigation
directory below its work type:

```text
.krcn/projects/<project-id>/local-data/work-documents/
  requests/<request-id>/<files>
  defects/<defect-id>/<files>
  tasks/<active|archived>/<task-id>/source/<source-id>/...
  _krcn/import-manifest.json
```

The `requests` parent is authoritative for request classification and the
`defects` parent is authoritative for defect classification. KRCN must not
infer or override the work type from document content. The identity directory
is the external work identity. A user may therefore place a document directly
under `requests/893614/` or `defects/475658/` and run the normal document
processing flow.

Year, source provider, original relative path, original file name, and source
provenance are manifest metadata. They are not navigation directories. The
same external number under `requests` and `defects` represents two different
Work Items and must never be merged.

Non-numeric identities require an existing reviewed Work Item whose project,
work type, and normalized external identity match the directory exactly. The
reviewed Work Item identity is reused; the document flow does not invent a new
identity. A combined folder that names several request identities requires an
explicit reviewed split mapping. KRCN does not guess either case.

The V2 `entries` collection contains only canonical direct-ID request and
defect references plus unchanged task and shared carry-forward records. An
excluded or unresolved legacy request or defect record is stored separately
in `legacy_preserved_entries` with its complete original manifest entry and a
strict `excluded-review` or `unresolved-review` preservation reason. It is not
a canonical V2 document, is not processed as one, and cannot weaken the
`requests/<id>/<file>` or `defects/<id>/<file>` invariant.

## Task and shared-document carry-forward

Layout version 2 changes request and defect navigation only. Existing task
documents remain under `tasks/<active|archived>/<task-id>/source/<source-id>`.
Their lifecycle bucket, task identity, provenance, and Work Item links are
carried forward without flattening or reclassification.

Historical `shared/requests` documents are not retained as a new canonical
navigation branch. A reviewed shared mapping projects the same digest and
source provenance into every allowed `requests/<request-id>` target. This may
create several logical source mappings while using fewer physical targets
after equal-content deduplication. An unresolved identity remains in the
legacy tree. An explicit `exclude` decision preserves the legacy source and
omits it from the current migration plan. Neither case permits guessing or
deletion.

## File identity and conflicts

SHA-256 is the document content identity. Equal content that resolves to the
same Work Item is deduplicated while all source provenance and Work Item links
are preserved in the manifest.

When different content has the same file name inside one identity directory,
every version is preserved with a deterministic digest suffix:

```text
<stem>__sha256-<first-12-hex><extension>
```

The mapping must not depend on discovery order. A repeated preparation over an
unchanged inventory produces the same targets, manifest digest, and exact plan
identity.

Migration metrics distinguish three cases:

- `collision_group_count`: target-name groups with more than one source mapping.
- `content_conflict_count`: collision groups containing more than one digest
  and therefore requiring deterministic suffixes.
- `deduplicated_group_count`: collision groups where at least two sources have
  equal content and are represented by one physical target while retaining all
  provenance and Work Item links.

## Manifest and authoritative state

The manifest records portable target references, content digests, sizes,
source provenance, Work Item links, semantic policy, and sensitivity classes.
Absolute machine paths are forbidden. Work Graph JSON remains authoritative
for work status and history. The manifest is authoritative only for the local
document inventory and its source-to-target mapping.

Current Work Items use layout version 2 document references after migration.
Append-only Work Events retain their historical references and are not
rewritten. Derived Work Graph and semantic SQLite indexes are rebuilt from the
current authoritative records.

## Processing lifecycle

A natural request such as `gpu-fusion gelen işlerini işle` follows one shared
service path:

1. Validate the manifest and current document digests.
2. Detect direct user additions in canonical identity directories.
3. Bind portable document references and digests to the related Work Items.
4. Rebuild the Work Graph SQLite projection when authoritative records change.
5. Incrementally rebuild the local semantic work index.
6. Verify that no source content entered Work Graph or the vector database.

A direct addition under a V2 request or defect identity directory is not
silently written into the manifest. The first `work.documents.process`
preparation returns a manifest-update exact plan. Its apply requires the exact
plan identity and explicit user approval, updates only the authoritative
manifest, and reports `work.documents.process` as the next operation. A second
preparation then produces the separate Work Graph and derived-index plan. This
boundary prevents one approval from authorizing two independently reviewable
user-data mutations.

The same exact-plan boundary applies when a file already present in the V2
manifest changes content. Preparation reports new and revised document counts
separately. A revision records a monotonically increasing `document_revision`
and the immediately preceding digest in `previous_sha256`; the plan identity
also covers the revision digest. Apply fails if either the file or manifest
changes after planning. Work Graph evidence and derived indexes are refreshed
only by the separately prepared follow-up operation.

An identity-specific natural request carries the requested external identity
to the same service. It must not silently fall back to processing a different
identity.

Large, binary, or sensitive documents remain preserved but are marked
`metadata-only` or `excluded-sensitive`. No remote provider receives document
content implicitly.

## Layout migration

Historical layout version 1 paths remain readable during a controlled
transition:

```text
requests/<year>/<id>/source/<source-id>/...
defects/<year>/<id>/source/<source-id>/...
```

Migration is a user-data mutation and uses `work.documents.migrate-layout`.
Preparation is read-only and returns an exact plan containing source and target
digests, conflicts, identity review requirements, legacy reference aliases,
and transaction rollback evidence. Apply requires the exact plan identity and
explicit user approval.

Ambiguous identities are supplied as reviewed decisions, for example
`--identity-decision corpsms=request` or
`--identity-decision legacy-error=defect` or
`--identity-decision unassigned=exclude`. Decisions are part of the exact plan
identity. Apply is allowed only when every included mapping is resolved. An
excluded mapping is preserved and not applied. Changing a decision requires a
new plan.

Apply stages and verifies the complete version 2 tree before making it current.
It provides transaction rollback while apply is in progress, but it does not
claim a post-apply rollback snapshot. A changed source, target, or manifest
digest invalidates the plan. Repeating a completed migration is a no-op.

Physical layout migration does not silently consume authority for Work Graph
updates. A successful migration reports `work.documents.process` as the next
operation. That operation prepares its own exact plan, updates current Work
Items through new revisions, and rebuilds derived indexes under the existing
approval rules. Append-only history remains unchanged.

The initial source directories used for import are never modified, renamed, or
deleted.

## Portability

A full KRCN user-home backup may include Work Documents. Standard project
capsules exclude their raw content and declare a project-local document
dependency instead. The layout change does not weaken either boundary.

# Readable Work Index contract

## Purpose

`WORK-INDEX.md` is a deterministic human-readable projection of authoritative
project Work Graph JSON records. It helps a human or a new model see active and
historical work without reconstructing state from chat history. It is derived
data and never replaces a Work Item, Work Event, checkpoint, handoff, or
authorization.

## Location

Layout v2 stores the projection at:

```text
projects/<project-id>/derived/work/WORK-INDEX.md
```

The ownership class is `derived`. The file may be deleted and rebuilt from
project Work Item records.

## Content boundary

The projection contains only:

- project ID and authoritative graph digest;
- counts by lifecycle status;
- Work Item ID, type, status, revision, and a bounded sanitized title;
- relation, evidence, and acceptance-criterion counts;
- deterministic truncation counts for historical work.

It never contains descriptions, acceptance-criterion text, evidence labels or
references, provenance, source content, absolute machine paths, secret values,
provider output, or private reasoning. Titles are normalized, bounded, and
redacted before rendering.

## Determinism and bounds

`config/work-index.json` defines the renderer revision, stable status and type
ordering, maximum listed items, maximum bytes, and maximum title length. Active
items are mandatory. If active items alone exceed an item or byte bound, the
renderer fails closed. Historical items are deterministically omitted from the
end of the stable order until both bounds are satisfied.

The document metadata binds the renderer, policy, Work Graph, and body digests.
No timestamp or machine locator enters the bytes. Equal Work Graph and policy
inputs therefore produce equal bytes on every supported client and device.

## Lifecycle

Normal `work.item.put` and new `work.import` exact plans include the readable
projection mutation. `work.documents.process` uses the same import boundary and
therefore updates the projection after its approved Work Graph mutation.

An existing or missing projection can be checked and rebuilt explicitly:

```text
krcn work index-readable <project-id>
krcn work index-readable <project-id> --apply --expected-plan <plan-id>
```

Preparation is read-only. Apply requires the exact plan and a verified dry run.
The derived mutation does not grant authority and does not weaken the separate
user-data approval required by a Work Graph change.

## Safety and recovery

Plan identity binds the authoritative graph digest, policy digest, rendered
document digest, and prior target state. Apply rebuilds the expected projection
from current Work Items and rejects stale graph, policy, or target state. Writes
use an atomic same-directory replacement and reject symlink or junction path
escapes. Batch import snapshots the prior projection and restores it together
with authoritative records if the batch fails.

Status and resume must continue to use authoritative Work Graph JSON when the
projection is missing, stale, truncated, or corrupt.

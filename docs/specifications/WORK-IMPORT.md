# Work Import

Work Import moves classified legacy requests, defects, tasks, subtasks, and decisions into one project's authoritative Work Graph. It does not copy source documents or source project files.

## Safety boundary

The importer separates discovery from persistence:

1. `inventory_work_source` reads a physical directory and returns only logical references, SHA-256 digests, and byte sizes.
2. A caller classifies that inventory into explicit WorkItem v1 candidates.
3. `prepare_work_import` validates the complete candidate batch and returns one exact plan.
4. `apply_work_import` requires that exact plan, mutation authorizations, and a freshly generated source inventory.

Physical source paths are never retained in the request, plan, manifest, result, work items, or evidence. Candidate text, references, and inventory references reject absolute paths and recognizable credential values. Sensitive source paths also fail closed.

## Batch validation

Candidates use project-scoped identifiers such as `gpu-fusion-request-893614`. Every relation target must exist in the current project graph or in the same import batch. The merged graph is validated for missing relation targets and dependency cycles before any write is planned.

The import plan pins:

- the source inventory digest;
- the authoritative graph digest before and after the import;
- every WorkItem and WorkEvent record revision;
- the current projection file state;
- every user-data and derived mutation;
- one wrapper plan identity for exact approval.

## Apply and recovery

Apply repeats all source, graph, revision, projection, manifest, and authorization checks before writing. It snapshots every target, writes authoritative item and event records, rebuilds the projection, and writes the project-scoped manifest last. If an in-process step fails, every touched target is restored to its prior bytes or removed if it did not exist.

The manifest is stored under:

```text
.krcn/projects/<project-id>/work/imports/<import-id>.json
```

The manifest contains logical source references and digests only. Repeating the same normalized candidate batch against the same source inventory produces the same import digest. A valid existing manifest and its WorkEvent evidence produce an `already-applied` no-op.

## API surface

```python
inventory = inventory_work_source(
    physical_source_root,
    source_id="mk-hub-isler",
    logical_root="mk-hub/isler",
)

plan = prepare_work_import(store, ownership, {
    "schema_ref": "schemas/work-import-request.schema.json",
    "schema_version": 1,
    "project_id": "gpu-fusion",
    "source_inventory": inventory.as_dict(),
    "candidates": candidates,
})

result = apply_work_import(
    store,
    plan,
    authorizations,
    expected_plan_id=plan.plan_id,
    current_source_inventory=fresh_inventory.as_dict(),
)
```

The application service and CLI adapters must rescan the physical source immediately before apply. They must expose `plan.public_summary()` and must not add the physical source root to a public or persisted payload.

## Current limitation

The first implementation provides in-process rollback across multiple files. A process or machine termination between file replacements cannot be made fully atomic by portable filesystem primitives. A later runtime integration can add a write-ahead recovery journal if crash recovery is required. The authoritative import manifest is written last, so an absent manifest never claims that a partial import completed.
# Application and CLI boundary

The shared application operation is `work.import`. Its arguments are:

```json
{
  "source_root": "<local absolute path>",
  "import_request": {
    "schema_ref": "schemas/work-import-request.schema.json"
  }
}
```

`source_root` is an execution-only locator. It is never included in the public
plan, result, manifest, WorkItem, or semantic index. The application rebuilds
the declared source inventory from the physical directory during planning and
again immediately before apply. Any difference blocks the import before a
write.

The CLI reads the portable import request from a file and receives the physical
source directory separately:

```text
krcn work import --source-root <directory> --request-file import.json
```

Planning does not write. Apply requires the exact returned plan identity and
the normal user-data approval.

# Work Graph contract

## Purpose

The Work Graph is the authoritative project record for requests, defects, tasks, subtasks, decisions, relations, lifecycle state, and delivery evidence. Orchestration state describes one execution attempt. It does not replace the durable work item.

## Storage

Layout v2 stores project records under:

```text
projects/<project-id>/work/items/
projects/<project-id>/work/events/
projects/<project-id>/derived/retrieval/work-graph-v1.sqlite
```

Work item and event JSON documents are user data. The SQLite database is a rebuildable projection. Status and history must remain available when the projection is absent.

## Identity and lifecycle

Work item identifiers are portable and stable. Supported types are `request`, `defect`, `task`, `subtask`, and `decision`. Supported states are `proposed`, `active`, `blocked`, `completed`, `cancelled`, and `archived`.

Every accepted revision creates one immutable work event. A completed item requires explicit evidence. Reopening a completed, cancelled, or archived item is a visible revision, never a silent rewrite.

## Relations and evidence

Relations connect work items in the same project. Dependency and parent graphs must be acyclic and every target must exist. Cross-project dependencies are represented through portable capsule dependencies, not by bypassing project scope.

Evidence may reference commits, branches, relative source files, tests, releases, or documents. Source file contents and absolute machine paths are not Work Graph evidence. A digest may bind evidence to an observed immutable value.

## Mutation and query rules

- Writes use `work.item.put` through one exact plan.
- User-data mutation requires explicit approval.
- Optimistic revision checks reject stale plans.
- `work.query` reads current authoritative status.
- `work.history` reads append-only lifecycle evidence.
- Derived projection failure cannot make SQLite authoritative.
- All clients use the shared application service.

## Resume behavior

`project.resume` includes active and historical Work Graph counts and a compact list of current items. Orchestration handoffs remain a separate execution section. Asking where work stopped must prefer Work Graph state over vector similarity.

## Portability

Both `thin` and `ready` project capsules include Work Graph JSON records. `thin` excludes the SQLite projection. `ready` may include it only after integrity verification. Neither mode includes source files, secrets, absolute locators, active locks, or active runtime ownership.

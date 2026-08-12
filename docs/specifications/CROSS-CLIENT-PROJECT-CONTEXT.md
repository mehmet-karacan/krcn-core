# Cross-client project context contract

## Purpose

KRCN clients must resolve the same registered project and resume state from any working directory without requiring a client-specific file inside every project. `project.resolve-current` and `project.resume` are read-only operations in the shared application service.

## Selection order

Selection is deterministic and uses this order:

1. An explicit project identifier or exact project name.
2. One registered project identifier or exact name mentioned in the user request.
3. A local project source binding that contains the current working directory.

When local project roots are nested, the deepest matching root wins. Multiple matches at the same selection level are ambiguous and must not be guessed. An unrelated working directory returns `matched: false` and is not an error.

## Path and source boundary

Local source binding locators are used only inside the shared service. Public output contains the binding identifier, locator kind, access mode, capabilities, policy references, and revision, but never the physical locator value.

Project source remains in place. Context resolution performs no scan, copy, index, network request, or mutation.

## Resume summary

`project.resume` adds a compact summary containing:

- registered project state
- persisted source-state count, file count, technologies, and digest
- current and stale information-record counts for the project
- up to five related orchestration handoffs
- active task count and safe next-action identifiers

An absent source state recommends a read-only project rescan. An empty information catalog recommends information extraction. An absent active task is reported explicitly instead of inventing prior work.

## Client behavior

Codex, Claude Code, OpenCode, CLI, plugins, SDK, MCP, and future clients use these operations without changing their semantics. Client bootstrap files only tell the client when to call KRCN. They do not duplicate matching, policy, ownership, or resume rules.

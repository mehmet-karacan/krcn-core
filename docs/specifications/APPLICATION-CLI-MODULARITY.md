# Application and CLI Modularity

## Stable facade

`krcn_core.application` remains the compatibility facade for existing clients.
`ServiceRequest`, `ServiceResponse`, `ApplicationServiceError`, and `OPERATIONS`
are owned by `application_contract.py` and re-exported by the facade. Existing
CLI, SDK, MCP, plugin, Codex, Claude, and OpenCode callers therefore retain the
same public import and serialization behavior.

## Explicit application registry

`application_registry.py` is the reviewed operation-to-method map. It must cover
the exact non-orchestration operation set. Missing methods, extra operations, or
registry drift fail during binding. The registry does not scan modules, load
plugins, infer handlers from names, or provide a permissive fallback.

Domain policy, authorization, storage, and provider decisions remain in their
own existing modules. Moving request and routing ownership does not move or
weaken those gates. Orchestration operations retain their separate application
service and are not duplicated in the general handler registry.

## CLI rendering boundary

Reusable table and display primitives live under `cli/renderers`. Human response
selection is an explicit operation registry. JSON output continues to serialize
the unchanged `ServiceResponse`; unregistered human operations retain the
generic status plus JSON-data fallback.

The main CLI module remains the entry point while parser families and domain
renderers can move incrementally behind this boundary. A missing reviewed human
renderer fails instead of silently switching the meaning of an operation.

## Parity and change rule

The request schema, response schema, public operation set, and handler registry
must be equal. Adding an operation therefore requires one reviewed contract
update and one explicit handler binding. Dynamic discovery is forbidden.

This refactor grants no authority and changes no exact-plan, approval, provider,
ownership, project isolation, stale, or verifier behavior.

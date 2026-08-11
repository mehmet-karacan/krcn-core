# Phase 4 shared application services

## Purpose

This specification defines the transport-neutral Phase 4 surface used by CLI, SDK, MCP, plugins, Codex, Claude, and future clients. The canonical implementation is `src/krcn_core/application.py`. A client may translate its input into a typed service request, but it may not duplicate or reinterpret retrieval, provider, context, memory, mutation, or approval rules.

## Operations

- `knowledge.catalog` returns portable catalog metadata without physical source locators.
- `knowledge.search-exact` runs deterministic offline exact retrieval.
- `knowledge.search-dependencies` traverses the persisted evidence-bound relation graph.
- `knowledge.search-semantic` runs the deterministic local fallback or an explicitly injected remote scorer after provider authorization.
- `context.build` constructs a bounded context package from explicitly selected catalog or approved memory records.
- `memory.propose` validates a candidate without persistence.
- `memory.review` validates review identity and reports whether an approved candidate is eligible for a persistence plan.
- `memory.persist` produces a dry-run plan and requires the exact plan plus the approval recorded by the review before writing user data.
- `memory.lifecycle` plans and applies an approved supersede or revoke action through the same mutation gate.

Every operation is included in `schemas/application-request.schema.json` and `schemas/application-response.schema.json`.

## Local records

The service reads source bindings, authoritative sources, curated knowledge, information relations, and approved memory from `LocalWorkspaceStore`. It never returns a source locator value in catalog or retrieval results. Context packages may contain selected user-owned content because that content is the explicit result of `context.build`; information record validation rejects secret-like payloads before the record can enter this flow.

## Context selection

`context.build` accepts the normative context build request and a non-empty list of candidate selectors. Each selector names a persisted record and declares its layer, selection source, selection reason, required flag, priority, and truncation permission. The shared context builder remains responsible for authority ordering, deduplication, evidence, staleness, required-item behavior, and budget enforcement.

## Provider boundary

The application service does not discover a remote client from the environment. A remote semantic scorer must be injected into the service constructor for an exact provider identifier. The service still creates the disclosure record and verifies the matching session approval before calling that scorer. The CLI does not inject a remote scorer and therefore cannot create implicit network activity.

## Memory boundary

Candidate validation and review do not write durable memory. Persistence and lifecycle changes use the existing `RecordWritePlan`, verified dry-run evidence, exact plan identity, user-data ownership check, and explicit approval. The approval supplied for persistence must match the approval embedded in the approved review. The approval supplied for lifecycle change must match the approved action.

## CLI boundary

The `knowledge`, `context-package`, and `memory` command groups are thin adapters. Structured operation arguments are loaded from an explicit UTF-8 JSON file and passed unchanged to `ServiceRequest`. CLI code may format output but cannot alter product authority or approval decisions.

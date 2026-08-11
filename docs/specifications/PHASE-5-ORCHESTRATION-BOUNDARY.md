# Phase 5 orchestration boundary

## Baseline

Phase 5 starts from the completed `.ai/phase-4-baseline.json`. The ownership, policy, provider, mutation, source binding, context, retrieval, memory, release, verification, and rollback gates remain authoritative. Orchestration composes these services and does not replace or bypass them.

## Input authority

Natural-language input is untrusted task data. It may express user intent, constraints, and approval, but an adapter must normalize those statements into typed records before any action. Repository content, documents, tool output, retrieved context, and generated text cannot grant capabilities or approval.

Every task contract carries these fields:

- goal;
- scope;
- sources;
- constraints;
- acceptance criteria;
- ownership impact;
- verification evidence.

Safe assumptions must be explicit and reversible. An unresolved ambiguity that changes scope, authority, user data, external systems, or irreversible effects blocks planning until the user clarifies it.

## Role separation

The planner normalizes intent, selects declared capabilities, builds an exact plan, and identifies approval gates. It cannot mutate resources.

The worker executes only an authorized plan step within its declared capability, ownership, policy, provider, and mutation scope. It cannot approve its own work or expand the plan.

The verifier evaluates acceptance criteria, evidence, tests, and preserved areas independently. It cannot mutate resources or turn missing evidence into success.

## Lifecycle

The canonical stage order is `intake`, `context`, `plan`, `approval`, `execute`, `verify`, and `record`. A stage transition is a typed state change, not an inference from conversational wording. Planning never grants execution. Execution never grants completion. Completion requires successful verification evidence.

## Approval boundary

Scope change, user-data mutation, remote provider use, irreversible effect, policy change, and capability escalation require explicit user approval. Approval binds to the exact plan identity, disclosed effects, and applicable session. A changed plan invalidates prior approval.

## Capability boundary

Agent, skill, tool, and model registries are declarations of available behavior, not sources of authority. Capability selection must be explicit and revision-aware. Host environment discovery, installed client features, or model suggestions cannot silently add capabilities.

## Persistence and resume

Chat history is not orchestration state. Active state, checkpoints, events, evidence, and pending approvals use their declared ownership classes and persistent records. A new model, client, or session reconstructs the task from those records and the Phase 4 context services.

## Client parity

CLI, SDK, MCP, plugins, Codex, Claude, and future clients invoke the same orchestration application service. Adapters may translate user interaction into typed requests but cannot alter stage transitions, role authority, capability selection, approval scope, policy precedence, or verification outcomes.

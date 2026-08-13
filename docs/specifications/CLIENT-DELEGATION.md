# Client Capability and Delegation Contract

## Purpose

KRCN Core classifies a request before an AI client starts project work. Meaningful
project work is delegated. The main agent acts as the coordinator and does not
silently perform the worker or verifier role.

The contract is client-neutral. Codex, Claude, OpenCode, plugins, and future
clients declare only the features available in the current session. A declaration
does not grant mutation, provider, model, or project authority.

## Session capability profile

Each session declares these capability facts:

- Native subagent support
- Parallel subagent support and the available slot count
- Per-agent model selection
- Agent cancellation
- Structured result support
- Isolated role execution for clients without native subagents

KRCN validates the complete declaration and selects one mode in this order:

1. `native-parallel`
2. `native-sequential`
3. `isolated-role-fallback`
4. `delegation-unavailable`

Mode selection is fail-closed. Contradictory or incomplete declarations are
rejected. A client without structured delegated results is not reported as a
working multi-agent client.

Profiles are bound to a portable session identifier. They contain no credentials,
endpoints, source content, or absolute paths. The canonical profile digest changes
when the session or its capabilities change.

## Request classification

Delegation is required when a registered project is matched and the request is
classified as analysis, design, implementation, verification, integration,
knowledge update, or work import.

General conversation, status reporting, and exact identifier lookup are explicit
coordinator exceptions. Unknown work classes are denied until the policy is
extended and reviewed.

## Coordinator boundary

For delegated project work, the main agent may:

- Classify the request
- Build a bounded context package
- Decompose the work and identify dependencies
- Assign subagents and prefer parallel execution for independent units
- Resolve dependencies and synthesize structured results
- Report client limitations honestly

The coordinator may not directly inspect project sources, perform domain analysis,
modify project sources, run project tests, or verify its own project work. Those
actions belong to worker and verifier roles under the existing KRCN authorization
and approval gates.

If delegation is required but unavailable, execution is blocked. The system must
not claim that a single-agent action was delegated.

## Parallel execution

Independent work units prefer parallel execution when at least two safe agent
slots are available. A native sequential or isolated-role fallback remains visible
in the decision when parallel execution is unavailable. These fallbacks preserve
role separation but never pretend to be parallel.

## Authority and persistence

Capability and delegation decisions are informational controls. They do not bypass
exact-plan approval, ownership, provider, model, database, or mutation policies.
Runtime integration must bind the decision to the same session and task context
before work begins.

# Client Capability and Delegation Contract

## Purpose

KRCN Core classifies a request before an AI client starts project work. Meaningful
project work is delegated. The main agent acts as the coordinator and does not
silently perform the worker or verifier role.

The contract is client-neutral. Codex, Claude, OpenCode, plugins, and future
clients declare only the features available in the current session. A declaration
does not grant mutation, provider, model, or project authority.

Mode selection never uses a client-name allowlist. Every client with a genuine
native subagent channel, parallel execution, and at least two declared slots gets
the same `native-parallel` decision. Optional cancellation, per-agent model
selection, structured payload, and isolated-role capabilities cannot downgrade or
block that native parallel channel.

## Session capability profile

Each session declares these capability facts:

- Native subagent support
- Parallel subagent support and the available slot count
- Per-agent model selection
- Agent cancellation
- Structured result support
- Isolated role execution for clients without native subagents

`native_subagents` means the session can start a separately identified agent and
return its lifecycle and failure status plus terminal text result to the
coordinator. Explicit agent cancellation remains the separate
`agent_cancellation` capability. Native result attribution is sufficient for
`native-parallel` and `native-sequential`; those modes do not require the agent
payload itself to conform to a KRCN JSON schema.

`structured_results` has the narrower meaning that a delegated result is already
machine-validatable against an explicit result contract, such as
`agent-result.schema.json`, without interpreting free text. It remains optional
for native modes and mandatory for
`isolated-role-fallback`, where KRCN has no native agent lifecycle channel to bind
the result to a distinct role execution.

KRCN validates the complete declaration and selects one mode in this order:

1. `native-parallel`
2. `native-sequential`
3. `isolated-role-fallback`
4. `delegation-unavailable`

Mode selection is fail-closed. Contradictory or incomplete declarations are
rejected. A client without a native attributed result channel or the structured
isolated-role fallback is not reported as a working multi-agent client.

Native free-text results are coordination input, not verified evidence. Before a
result can complete a runtime work unit or become durable state, the existing
task, evidence, lease, fencing, verification, ownership, and approval contracts
still apply. A capability declaration never upgrades free text into authority.

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
- Resolve dependencies and synthesize attributed delegated results
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

## Application and CLI operations

`client.capabilities` validates one complete session declaration and returns a
credential-free capability profile. `client.delegation` validates the same profile,
classifies one work request, and returns the coordinator boundary and delegation
decision. Both operations are read-only and reject apply mode.

The CLI exposes the same transport-neutral operations:

```text
krcn client capabilities --help
krcn client delegation --help
```

The delegation command requires an explicit matched or unmatched project result.
It returns `ok` for native parallel delegation or a coordinator exception,
`degraded` for allowed sequential and isolated-role fallback, and `blocked` when
meaningful project work cannot be delegated. A blocked CLI decision uses a nonzero
exit code after printing the structured decision.

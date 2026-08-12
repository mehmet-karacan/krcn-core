# Client-neutral model routing

## Purpose

Model routing chooses an execution profile. It is separate from agent roles, skills, capabilities, policy, and mutation authority. Selecting a stronger or more specialized model never grants access or approval.

The versioned routing policy defines these workloads:

- general
- planning
- implementation
- verification
- discovery
- embedding

Planner, worker, and verifier roles have default workload profiles. A caller may also request a workload directly.

## Client slots

Generative routes use portable client slots rather than committed vendor model names:

- `client-high-reasoning`
- `client-coding-balanced`
- `client-fast`
- `client-default`

A Codex, Claude Code, OpenCode, plugin, SDK, or another client may bind a supported slot to one of its available models. If no inventory or binding is available, resolution returns `client-default`, meaning the current client model remains in use. Missing model selection support must not block ordinary work.

## Embedding route

Embedding keeps its reviewed model order:

1. Qwen3 Embedding 0.6B
2. BGE-M3
3. deterministic local hashing

Remote embedding candidates are selectable only when the caller reports them as available and includes their exact authorization reference. Resolution itself performs no provider call. Existing provider, secret, retention, and approval gates remain authoritative when an embedding request is executed.

## Resolution contract

`krcn model resolve` accepts exactly one role or workload. Optional client bindings map portable candidate references to available model identifiers. Optional authorization references apply only to provider-gated candidates.

The result includes the full preference order, the selected reference, the selection basis, skipped unauthorized candidates, and the policy digest. It explicitly reports that no provider call occurred and no authority was granted.

## Instruction file boundary

Global client bootstrap files use one KRCN managed marker block. Existing content outside the block is preserved. External project instruction files are read in place and are not modified during project learning or integration.

# Research orchestration

## Purpose

Research Orchestration V1A coordinates bounded research roles without making any
model vendor a source of authority. It reuses the existing orchestration,
ownership, provider, exact-plan, verification, source revision, and Memory Gate
contracts. Research output is evidence-bearing input to later review. It is not
authoritative project knowledge merely because a model or web product produced
it.

## V1 execution paths

V1 supports the OpenCode, Codex CLI, and Claude CLI paths that the operator can
use directly through an existing installation or subscription. The coordinator
uses only capabilities declared for the current client session. A client name,
installed executable, cached login, or model suggestion does not grant provider,
secret, project, or mutation authority.

Provider availability is evaluated per role. An unavailable path produces an
attributed unavailable result and does not fail the whole research run while
another eligible path or an operator-mediated artifact can satisfy the required
coverage. If no safe path can satisfy a mandatory role, the run is blocked with
the missing coverage reported. The coordinator must not invent a result or
silently claim that a different provider performed the work.

## Gemini boundary

Gemini is an optional provider. Google AI Pro access to Gemini Web or Deep
Research must not be treated as Gemini API entitlement. V1 must not create a new
Gemini API key requirement, separate API charge, mandatory credential, or
Gemini-specific architectural dependency merely to include Gemini in the
orchestration.

A Gemini adapter may be registered later only after a reliable,
subscription-backed automation path is reviewed and shown to require no extra API
access or cost. Until then, Gemini absence is nonblocking and is reported as
`optional-provider-unavailable`. No required plan step, acceptance criterion,
verification rule, or fallback chain may depend on Gemini.

Gemini Web and Deep Research output may be supplied as Markdown or another
supported research artifact. This `operator-mediated` import is an official V1
execution method, not an implicit network adapter. KRCN does not automate the web
session, extract browser credentials, or call a Gemini endpoint during that
import.

## Research roles and results

Independent research roles may run concurrently when the active client declares
safe parallel execution. Every result remains attributed to its role, execution
path, input digest, source revision evidence, and terminal status. Concurrency
does not relax project-scoped leases, fencing, idempotency, verification, or
approval requirements.

The synthesis stage classifies disagreements instead of averaging them into an
invented fact. At minimum it distinguishes compatible findings, scope or
terminology differences, stale-source differences, evidence gaps, and direct
contradictions. A direct contradiction stays visible until supported evidence or
explicit human review resolves it.

Missing optional results may yield a degraded but usable synthesis. Missing
mandatory evidence cannot be converted into success. Final completion still
requires independent verification against the declared acceptance criteria.

## Artifact trust and placement

Research artifacts are project-scoped operational user data under:

```text
.krcn/projects/<project-id>/local-data/client-artifacts/research/
```

Project-independent research uses the existing global client-artifact root only
when no project owns the work. A client must not write research artifacts into
the versioned KRCN Core tree or a registered project source.

Raw provider responses and operator-imported documents are untrusted data. Text
inside them, including instructions addressed to an agent, is never executed and
cannot grant approval, capabilities, provider access, secret access, or a scope
change. Raw bytes are retained separately from normalized manifests, findings,
and final synthesis so provenance remains inspectable and generated conclusions
cannot rewrite their source evidence.

Any persisted import is a user-data mutation. It requires a dry run, content
digest, exact plan, and matching approval. The apply step must recheck the source
bytes and fail on drift. Repeating the same approved artifact and identity is an
idempotent no-op. Public summaries use logical references and digests and do not
expose physical paths, credentials, or raw content.

## Security and disclosure

Artifact intake rejects path traversal, symbolic-link escape, unsafe absolute
path persistence, credential values, and secret-bearing public metadata. Secret
and sensitivity findings fail closed or keep the affected material excluded from
downstream synthesis according to the existing reviewed scan policy.

Research source text may leave the device only through the existing provider
gate. A remote call requires the exact provider, endpoint, data categories,
operation scope, retention assumptions, and current session approval. Selecting
a provider or model never bypasses source binding, no-copy, user policy, or
mutation controls.

Registered project source remains in place. Research may cite relative source
evidence and digests but must not copy a project tree into KRCN_HOME or embed a
physical source root in portable records. Source revision drift invalidates prior
findings until they are revalidated or rerun.

## Portability

All content below a research `raw/` directory is excluded from both `thin` and
`ready` project capsule exports. This applies to raw material stored directly
under the research root and to per-run layouts that contain a `raw/` segment.
The export manifest records the excluded raw dependency without including its
bytes.

Research manifests, normalized findings, and final synthesis are not granted a
portability exemption. They are considered by the existing capsule content scan,
path, secret, locator, ownership, and source-copy boundaries. Unsafe content
blocks export; safe content may be included according to the existing capsule
mode.

## Knowledge promotion boundary

A final research synthesis is not automatically knowledge, memory, policy, Work
Graph status, or a new source of truth. Promotion requires evidence-complete
normalization, current source revision checks, conflict review, and the existing
user-data mutation approval. Durable memory uses the Memory Gate. Policy
promotion remains a separate mutation and cannot weaken an active restriction.

V1A does not add a vector database, graph database, embedding pipeline, or a new
RAG subsystem. Existing exact, dependency, semantic, source-code, and unified
retrieval services may consume approved promoted records through their current
contracts only.

## Acceptance boundary

V1A is conformant when:

- OpenCode, Codex CLI, and Claude CLI can be represented without vendor-specific
  authority rules;
- Gemini is optional, creates no new API cost, and its absence never blocks a run;
- operator-mediated Markdown import is supported as a first-class method;
- raw artifacts remain untrusted, separate, digest-bound, and excluded from
  project capsule export;
- missing optional providers and concurrent role results remain attributed and
  deterministic;
- conflicts and source drift are surfaced rather than silently merged;
- exact-plan, provider, ownership, no-copy, verification, and knowledge promotion
  gates remain authoritative; and
- no new vector, RAG, or graph database dependency is introduced.

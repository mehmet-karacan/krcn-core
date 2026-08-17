# Adaptive Routing

## Purpose

Adaptive Routing creates one deterministic and explainable decision about how
reviewed work would be executed. Phase 23 operates only in shadow mode. The
decision does not change coordinator, queue, delegation, model, provider,
admission, or authorization behavior.

## Decision axes

The following records remain separate:

- work classification describes the kind of work;
- route decision describes the proposed execution shape;
- delegation decision describes the real client transport capability;
- model assignment selects a model for a reviewed step;
- admission decision decides whether a new claim may start now;
- authorization grants an exact effect scope.

A route record must never contain or imply the other decisions.

## Content boundary

`RouteRequest` contains identifiers, digests, classifications, bounded numeric
features, capabilities, logical resource references, authority observations,
and budgets. It never contains request text, prompt text, model output,
credentials, physical paths, source code, or document content.

`RouteDecision` contains the selected route, reason codes, rejected routes,
estimates, and exact request and policy bindings. It declares:

- `mode: shadow`;
- `enforcement_applied: false`;
- `grants_authority: false`;
- no delegation decision;
- no model assignment;
- no admission decision.

## Route modes

- `coordinator-response`: status and exact lookup projections;
- `direct-read`: one bounded read-only unit;
- `single-worker`: one meaningful isolated problem;
- `sequential-dag`: dependency ordering or resource conflict;
- `parallel-dag`: independent and disjoint subproblems with sufficient budget;
- `review-only`: an exact approval is still required;
- `blocked`: a non-bypassable safety precondition is missing;
- `recovery-required`: a claim exists without a terminal receipt.

## Hard gates

Hard gates run before soft routing. They cannot be weakened by model output,
policy score, client preference, or caller-provided reason codes.

The initial gates cover:

- missing required capability;
- pending effect claim without terminal receipt;
- secret data requiring a remote provider;
- missing provider assurance for a required remote provider;
- exhausted input, output, cost, latency, or concurrency budget;
- missing authoritative project or Work Item context;
- stale source revision;
- missing sandbox for mutation;
- missing independent verifier for high or critical risk;
- missing exact approval for an approval-required mutation.

## Resource conflict

Resources are logical references. When different nodes reference the same
case-folded resource and at least one access is `write`, the request has a
resource conflict. A conflicted request cannot select `parallel-dag`.

## Shadow comparison

The existing Execution Coordinator route remains authoritative for behavior.
Shadow comparison maps detailed worker routes to the existing
`delegated-dag` family and records one of:

- `matched`;
- `mismatch`;
- `not-comparable`.

Every comparison declares `behavior_changed: false`. A mismatch is evidence
for policy evaluation, not permission to enforce the new route.

## Append-only decision record

`routing.record` prepares an exact runtime-owned write for one deterministic
route decision. The record key is derived from the decision digest, so the same
decision is idempotent and a conflicting replacement is rejected. Planning is
read-only. Apply requires the exact plan ID and a verified mutation
authorization, but runtime ownership never turns the record into user,
provider, model, queue, or execution authority.

Records live under the project or global runtime routing collection. They keep
the strict decision, portable scope identities, canonical observation time,
and a record digest. They never contain raw prompts, model output, source
content, secrets, or physical paths.

## Determinism and compatibility

The policy, request, decision, and comparison records use strict field sets,
canonical ordering, and SHA-256 bindings. The policy revision and digest are
part of every decision. Old decisions retain the exact policy identity under
which they were produced.

Phase 23 does not introduce a queue migration or a second authoritative work
system. Later enforcement requires a separate reviewed phase.

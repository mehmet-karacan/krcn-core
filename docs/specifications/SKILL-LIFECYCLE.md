# Controlled Skill Lifecycle

## Purpose

The skill lifecycle boundary turns repeated, reviewed operational evidence into
content-free skill metadata. It does not create skill code, edit an active
skill, write the registry, select a model, or grant execution authority.

The lifecycle is:

```text
candidate
  -> evaluated
  -> approval-required
  -> active
  -> deprecated or retired

deprecated
  -> retired
```

A candidate cannot skip a state or promote itself.

## Candidate and dedupe boundary

`schemas/skill-candidate.schema.json` stores only portable identifiers, logical
source references, source/repetition digests, proposer identity, proposer model
digest, and the candidate digest. It forbids code, skill content, physical
paths, secret values, and authority.

Human-readable actor references are labels, not security identities. Candidate,
evaluation, approval plan, and lifecycle records bind stable SHA-256 actor
identity digests. Proposer, evaluator, verifier, and approver digests must be
pairwise distinct. Changing a reference to an alias therefore cannot bypass
self-promotion or independent-verification checks. Finalization must present the
exact approver identity digest already bound into the approved plan.

Candidate dedupe groups records when they share either their reviewed source
digest or at least one repetition digest. The canonical candidate is selected
deterministically. Duplicate candidates are preserved; their evidence is not
double-counted.

## Evaluation gate

`schemas/skill-evaluation.schema.json` binds the evaluation to:

- the exact candidate digest;
- a project fixture digest;
- an evaluation-run digest;
- independent evaluator and verifier identities;
- different tested and verifier model digests;
- an environment digest;
- trial count, passed trials, score, and timestamp.

`config/skill-lifecycle-policy.json` defines the minimum trials, minimum passed
trials, trial pass-rate threshold, and score threshold. A failed or insufficient evaluation remains
evidence but cannot enter `approval-required`.

The evaluator and verifier identities must differ. The tested and verifier
model digests must also differ. This is an evaluation invariant, not permission
to call either model.

## Registry mutation gate

A passed evaluation may prepare
`schemas/skill-registry-change-plan.schema.json`. The plan targets the
user-owned logical registry namespace and uses the existing Mutation Gate. It
is reversible, requires a verified dry run, and always requires matching user
approval.

The plan binds:

- candidate and evaluation digests;
- expected previous registry digest;
- proposed registry record digest;
- rollback target;
- optional supersession target;
- exact mutation plan ID.

This module deliberately has no registry apply function. The registry owner
must independently perform and verify the exact approved write. Finalization
only produces content-free lifecycle metadata after receiving the matching
`MutationAuthorization`. The candidate proposer cannot be the finalizing
actor.

Deprecation and retirement create new exact plans. An activation approval never
authorizes a later lifecycle transition.

## Safety invariants

- Candidate, evaluation, plan, and lifecycle records are strict and
  digest-bound.
- Actor alias strings never replace stable identity digest comparison.
- Unknown fields and digest tampering fail closed.
- Public records contain no skill code, skill content, physical path, secret,
  provider payload, or private reasoning.
- Every public record asserts `grants_authority: false`.
- A candidate never modifies the active registry.
- Rollback and supersession are explicit and digest-bound.
- The registry remains a separate owner and source of truth.

## Python API

- `load_skill_lifecycle_policy`
- `build_skill_candidate` / `parse_skill_candidate`
- `find_skill_candidate_duplicates`
- `build_skill_evaluation` / `parse_skill_evaluation`
- `prepare_skill_activation` / `parse_skill_registry_change_plan`
- `finalize_skill_registry_change`
- `prepare_skill_state_change`
- `parse_skill_lifecycle_record`

Application and CLI exposure is intentionally outside this package. Adding it
later must preserve the same exact-plan, approval, ownership, and independent
verification boundaries.

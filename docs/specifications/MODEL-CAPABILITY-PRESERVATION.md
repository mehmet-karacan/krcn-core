# Model Capability Preservation

## Purpose

KRCN adds safety and durable context without turning a capable model into a
rigid form filler. The capability gate compares the same reviewed golden cases
with baseline model execution and KRCN-enabled execution.

The gate is local and deterministic. It consumes normalized measurements and
does not call a provider, execute a model, or grant authority.

## Hard constraints

Hard constraints are blocking and cannot be weakened by a model, client, route, or benchmark.

The V1 hard constraint set covers:

- authority boundaries;
- evidence integrity;
- output contract validity;
- secret protection;
- side-effect boundaries.

Any KRCN-enabled hard constraint violation blocks the evaluation. Critical
golden cases allow no capability or normalized score regression.

## Soft guidance

Solution method, research order, alternative generation, counter-evidence,
assumption challenge, and lazy retrieval are soft guidance. They describe
desired behavior without prescribing private reasoning steps.

KRCN supplies the minimum required context, retrieves lazily, and does not use
full history by default. A model may challenge an incorrect assumption and
offer alternatives supported by evidence.

## Golden A/B comparison

The versioned golden set contains controlled identifiers, criticality, policy
coverage, and evaluation traits. It contains no prompt text, source content,
secret, or physical path.

Each baseline and KRCN-enabled result supplies only:

- execution digest;
- task success and verifier outcome;
- normalized score;
- input and output token counts;
- latency, agent call, and human intervention counts;
- controlled hard constraint violation identifiers.

General success and average score may regress by at most 200 basis points.
Critical regression and hard constraint violations must remain zero. Token,
latency, agent call, and human intervention overhead are visible advisories and
cannot hide or weaken capability failures.

## Privacy and authority

The evaluation persists no raw prompt, raw output, source content, private
chain-of-thought, model credential, or physical path. Evaluation identity binds
the policy digest, golden set digest, normalized case results, aggregate,
blocking reasons, and advisories.

The evaluation does not choose a model. Model routing and the later model
decision service may consume a passing result, but provider approval, mutation
approval, client capability, and verifier rules remain independent.

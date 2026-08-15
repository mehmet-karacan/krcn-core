# Retrieval Golden Evaluation

## Purpose

KRCN measures retrieval quality before adopting a more expensive embedding
model, chunker, database, or service. The benchmark is engine-neutral: every
retrieval implementation must return the same bounded observation contract and
is then scored by the same evaluator.

The golden set is derived from user needs, not from the current ranking output.
It covers exact identifiers, typographical lexical search, Turkish and English
business concepts, Java symbols, dependency impact, continuity resume, PL/SQL
package and procedure lookup, project isolation, and stale-revision rejection.

## Quality measures

Ranking cases are measured with Recall@K, mean reciprocal rank, nDCG@K, and
exact-ID top-one accuracy. Safety cases are measured separately. A run cannot
pass if it accepts stale evidence, leaks a hit from another project, fails a
critical case, or exceeds the configured p95 latency threshold.

The result digest excludes observed latency because timing is environment
dependent. It binds the suite, engine profile, ranked outcomes, safety outcomes,
quality metrics, critical failures, and pass decision. Latency remains visible
as measurement evidence.

## Evidence boundary

The evaluator does not call a model or provider, mutate user data, copy source
content, or grant authority. An engine adapter must collect observations through
its normal retrieval boundary and preserve its existing stale, project scope,
provider, and source-content rules. Incomplete case coverage and malformed or
physical-path evidence fail closed.

Remote engines remain subject to their normal provider approval. Supplying a
remote observation to this evaluator does not prove or grant that approval.

## Scale fixtures

Scale documents are generated lazily from a versioned synthetic policy. The
committed repository stores only the generator, policy, and digest-bound
manifest, not a large generated corpus. Profiles cover 128, 1,000, 10,000, and
50,000 documents with bounded query, project, and payload sizes.

Every generated document has a deterministic logical reference and revision
digest. It contains controlled Java, Python, SQL, PL/SQL, business, and
continuity vocabulary but no project source, secret, user path, or provider
content. This permits comparable p50/p95 and memory measurements without
turning proprietary project data into a benchmark fixture.

## Comparison workflow

1. Select the same golden revision and scale profile.
2. Run each candidate engine or configuration through its reviewed adapter.
3. Record all cases, including rejections and empty results.
4. Evaluate observations with this service.
5. Compare quality, p50/p95 latency, storage, provider calls, and cost.
6. Adopt a more expensive model or infrastructure only when the measured gain
   satisfies the product decision threshold.

Golden results are evidence, not policy or execution authority.

# Phase 8 local hybrid retrieval

The Phase 8 retrieval layer is a rebuildable SQLite index under the active KRCN user home. It combines exact matching, SQLite FTS5, deterministic hashed vectors, dependency proximity, information authority, and availability in one explainable ranking.

## Storage boundary

The index is written only to `.krcn/derived/retrieval/hybrid-v1.sqlite`. It is derived data and may be deleted and rebuilt. It contains approved KRCN catalog text and vector representations needed for retrieval. It does not read or copy external project files, external documents, source locators, database rows, or secret values.

Index creation uses an exact mutation plan, verified dry-run evidence, a staging database, SQLite integrity verification, and atomic replacement. Derived rebuilds do not require user-data mutation approval. A catalog digest mismatch makes an existing index stale and search fails closed until rebuild.

## Vector semantics

The local vector is not a remote embedding and does not claim language-model semantics. It is a 192-dimensional signed feature hash over normalized words and character trigrams. It improves deterministic typo and lexical-shape recall without network access, model downloads, credentials, or provider disclosure.

## Common ranker

Every hit publishes a score breakdown with these fixed Phase 8 weights:

| Signal | Weight | Meaning |
| --- | ---: | --- |
| Exact | 0.30 | Exact field match or normalized phrase containment |
| FTS | 0.25 | SQLite full-text relevance |
| Vector | 0.25 | Local deterministic vector similarity |
| Dependency | 0.10 | Distance from explicit seed records in the relation graph |
| Authority | 0.05 | Authoritative-source or curated-knowledge priority |
| Availability | 0.05 | Current versus unavailable or stale state |

The output includes catalog, query, index, and result digests. It contains evidence metadata, never physical source paths or retrieved payload text.

## Evaluation and scale decision

`config/retrieval-evaluation.json` is the versioned four-case quality set. It covers exact retrieval, typographical vector recall, deployment retrieval, and dependency recall. The acceptance threshold is 1.0 for recall at five and mean reciprocal rank on this reference set.

`tools/benchmark_hybrid_retrieval.py` measures actual index build and query latency on generated catalogs. The Phase 8 reference measurement covered 101 and 1001 catalog entries. SQLite was selected only after these measurements stayed inside the versioned thresholds in `.ai/retrieval-performance-baseline.json`.

The current vector stage scans the indexed candidate set. Candidate narrowing or a dedicated local vector extension becomes justified when real catalogs regularly exceed the measured reference size or breach the versioned latency threshold.

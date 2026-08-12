# Source code RAG

## Storage boundary

Each registered project has one rebuildable SQLite database under `.krcn/derived/retrieval/source-code-v1/<project-id>.sqlite`. The database contains logical project identity, relative paths, source hashes, chunk ranges, safe symbol names, and vectors. It never contains the physical source root or persisted source text.

## Chunk identity

A chunk is bound to the project ID, relative path, exact file digest, character range, line range, and chunk digest. Chunk text is read only while producing a vector or serving an approved local retrieval result. The index stores the digest and vector, not the text.

## Incremental rebuild

An unchanged file may reuse its previously verified chunk rows when the policy digest, embedding profile, file size, and file digest still match. Changed and new files are read and reprocessed. Files absent from the current discovery state are omitted from the replacement database. The complete replacement is staged, verified with SQLite integrity checks, and installed atomically.

An index is current only when its project ID, binding ID, binding revision, source digest, policy digest, embedding profile, dimensions, file inventory, and chunk inventory match the active project source state. A source rebind therefore makes the previous index stale even when every source file digest is unchanged. The rebuild may reuse verified chunks, but it must publish new metadata bound to the current binding revision before retrieval is allowed.

## Sensitive and generated source boundary

Shared import policy excludes dependency trees, generated output, build output, vendor bundles, legacy AI backups, archives, binaries, dumps, logs, local environment files, and secret-key files before indexing. The source index also scans supported text in memory for configured secret, credential, machine-locator, personal-path, and network-address detector classes. A matching file is skipped as `sensitive_content`; matched values are not returned, logged, persisted, or embedded.

The detector set is part of the source-index policy digest. Tightening the detector policy makes an existing index stale and requires a safe rebuild. Project-specific clients cannot weaken this boundary.

## Retrieval

Retrieval combines relative-path and symbol exactness, FTS over non-content metadata, and deterministic vector similarity. A result identifies the relative path and exact source range. When content is requested, KRCN resolves the registered read-only binding, verifies the current file and chunk digests, and reads that range from the source in place. A mismatch fails closed and requires reintegration.

## Provider boundary

The baseline uses the local `deterministic-hashing` profile. The reviewed remote order remains Qwen3 followed by BGE-M3. Source code may be sent to a remote embedding provider only through an explicit integration, exact provider request, disclosure, and matching session approval.

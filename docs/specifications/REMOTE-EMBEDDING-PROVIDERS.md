# Remote embedding providers

## Purpose

KRCN Core may use an explicitly configured OpenAI-compatible embedding endpoint to generate dense vectors for approved knowledge content and retrieval queries. Offline deterministic retrieval remains the default and final fallback.

## Reviewed model order

The versioned model catalog defines this order:

1. `Qwen3-Embedding-0.6B` is the primary multilingual and code-retrieval model.
2. `BGE-M3` is the remote fallback and provides a mature multilingual retrieval alternative.
3. `deterministic-hashing` is the offline fallback and never transmits data.

The order is explicit and deterministic. Host model discovery, OpenCode model lists, or provider suggestions cannot change it automatically.

## Local integration

The endpoint, selected reviewed profile IDs, retention assumptions, and secret reference live in a user-owned integration record under the active `.krcn` home. The record contains no literal credential. An `opencode://<provider>/api-key` reference allows the dedicated local secret provider to read an explicitly supplied OpenCode configuration file without copying the value.

OpenCode configuration is never scanned during repository bootstrap, doctor, import, test, or offline retrieval. A caller must explicitly select the integration and configuration path for a provider operation.

## Approval and disclosure

Every remote embedding call requires a provider request bound to:

- the reviewed provider profile;
- the exact HTTPS endpoint;
- one data category: approved knowledge content, query text, or synthetic access test;
- the `embedding-generate` operation scope;
- retention assumptions;
- one session identifier.

The matching session approval is verified before the credential is resolved or the network transport is called. A fallback chain may try the next reviewed remote profile only when that profile has its own exact provider request and matching approval. If all reviewed remote profiles fail, the operation stops with an explicit instruction to use the offline deterministic fallback.

## Vector safety

Responses must contain exactly one finite, non-zero vector per input, preserve input ordering, and match the reviewed dimension. Vectors are normalized before use. Public summaries exclude input text, endpoint value, credential reference, and credential value.

Changing the model or vector dimension creates a different vector space. Stored document vectors and query vectors must use the same profile. Switching to a fallback profile for search therefore requires a matching index representation or an index rebuild.

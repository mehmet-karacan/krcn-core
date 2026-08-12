# JSON document format

## Purpose

KRCN Core separates the byte representation used for stable identities from the representation stored as a document. Human-readable storage must not weaken exact-plan, digest, or integrity guarantees.

## Canonical identity representation

Hash, plan identity, comparison, and content identity calculations use compact UTF-8 JSON with recursively sorted object keys and no insignificant whitespace. A caller must choose explicitly whether the historical contract includes a trailing newline. Canonical identity bytes are an internal calculation form and are not the default persisted document form.

## Persisted document representation

JSON files produced by KRCN Core use:

- UTF-8 without a byte order mark;
- two-space indentation;
- unescaped Unicode text;
- deterministic key ordering for generated records;
- one trailing newline;
- strict rejection of non-JSON numeric values.

Repository source JSON preserves its declared key order while applying the same indentation, Unicode, and trailing-newline rules. `python tools/format_json.py --check` verifies every versioned JSON source document. Repository verification also rejects invalid or nonconforming candidate JSON files.

## Compatibility and safety

Readers continue to accept valid compact historical records. A formatting difference does not change payload meaning, policy authority, source revision, or semantic content digest. Existing user data is never rewritten merely because a core update introduces a newer display format. A user-authorized migration may normalize historical records while preserving their parsed value and integrity evidence.

Project-home manifests, local records, deployment journals, installation state, migration output, derived JSON, and portable backup JSON use the shared readable writer. SQLite internal JSON values and canonical bytes embedded in digest calculations are not standalone JSON documents and may remain compact.

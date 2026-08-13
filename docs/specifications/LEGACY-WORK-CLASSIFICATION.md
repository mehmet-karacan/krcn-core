# Legacy Work Classification

The legacy work classifier is a read-only adapter in front of Work Import. It
uses directory names and file metadata to produce deterministic WorkItem v1
candidates for one explicit project. It never copies source documents or
persists their contents.

`aktif` and `arsiv` are source buckets. They map to `active` and `archived`;
neither bucket proves completion. A completed status still requires separate
authoritative evidence.

Numeric request and defect directories provide external identities. Suffix
directories such as `468337_2` are treated as additional evidence for the same
identity. A combined directory such as `893614_893609_893508` produces three
project-scoped candidates with evidence-bound `relates-to` links.

Root Markdown files with a configured task identity become task candidates.
Filename suffixes such as `-B` do not create a new authoritative task identity.
Multiple files claiming the same base identity stop import readiness and
produce a review record. The classifier does not silently merge those files.

Every source file is represented only by a portable logical reference, SHA-256
digest, and byte size. Binary files are hashed but never read into candidate
text. Sensitive paths, secret-shaped references, symbolic links, absolute
paths, and changing files fail closed through the shared Work Import inventory
boundary.

An import-ready result exposes an object that conforms exactly to
`schemas/work-import-request.schema.json`. Applying it remains a separate exact
plan and user approval operation.

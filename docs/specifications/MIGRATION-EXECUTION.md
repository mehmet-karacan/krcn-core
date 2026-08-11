# Migration execution contract

## Trusted registry

Release manifests contain migration identifiers only. An identifier becomes executable only when KRCN Core code registers both its version transition descriptor and its trusted JSON transform. Manifest content cannot provide Python, shell, SQL, template, or expression code.

## Planning

The migration scope is a portable local-data target declared by trusted core code. Generic migration may target runtime, user-data, or derived ownership. Secret targets are prohibited. User policy targets require a dedicated semantic preservation contract and are not accepted by the generic migration engine.

During final deployment dry-run, every JSON document in scope is parsed and passed to the transform without filesystem access. The output is serialized canonically. The transform is run again on its own output; a different second result rejects the migration as non-idempotent.

Every changed record produces an exact update mutation containing its target reference, ownership, previous SHA-256, target SHA-256, and planned document. Generic migrations cannot create or delete records.

## Application

Migration application starts only after verified backup and managed core application. All migration targets and authorizations are revalidated before the first migration write. User-data writes require explicit approval. Writes are atomic and their resulting hashes are verified.

The installation state records the new schema version and completed migration identifier only after all managed files, migrations, derived actions, and mandatory verification succeed.

## Failure

A migration failure cannot produce a successful installation state. The deployment remains recoverable from its local backup and the merge orchestrator must roll back all prior effects.

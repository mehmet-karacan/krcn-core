# KRCN Core boundaries

## Origin and stewardship

KRCN Core was conceived and architected by **Mehmet KARACAN**. This repository is the canonical engineering home for evolving that architecture while preserving its core principles, provenance, and user-data safety guarantees.

## Target model

KRCN Core will connect these entities through shared identity and relationship models:

- projects and physical source locations;
- documents and authoritative-source references;
- work items, requests, tasks, and checkpoints;
- decisions, evidence, and generated artifacts;
- context packages and durable memory;
- agents, skills, tools, and model routing.

## Deployment boundary

The default update policy is:

| Class | Examples | Update behavior |
|---|---|---|
| Core | CLI, engines, schemas, policies | Replace through a controlled release |
| Runtime | active tasks, checkpoints, events | Preserve |
| User data | projects, documents, requests, decisions, memory | Preserve |
| Derived | indexes, embeddings, caches | Migrate or rebuild |
| Secrets | tokens, passwords, connection credentials | Never manage through Git |

This boundary will become a machine-validated ownership manifest.

## Update contract

The target flow is:

`inspect -> diff -> dry-run -> backup -> compatibility check -> apply -> migrate/rebuild -> verify -> rollback`

No step may silently mutate user-owned data.

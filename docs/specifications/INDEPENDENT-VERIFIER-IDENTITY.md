# Independent Verifier Execution Identity

## Purpose

KRCN requires every worker and verifier execution to carry a digest-bound
identity. A verifier label, handler name, or client declaration is not proof of
independence.

## Identity contract

An execution identity binds the task, exact plan, step, role, actor, session,
assignment, and runtime kind. It contains digests only, discloses no physical
path or credential, and grants no authority.

The trusted host registers the actor digest and runtime kind for each handler.
A client-provided identity must match that registration before the handler can
run. A client cannot replace the registered actor by changing request data.

## Verifier independence

A verifier actor and assignment must be independent from every worker it can complete.
The verifier identity must:

- use the verifier role;
- bind to the same task and exact plan as the worker evidence;
- bind to its own verifier step;
- use an actor digest different from all covered workers;
- use an assignment digest different from all covered workers;
- match the trusted verifier handler registration; and
- bind every evidence record to its execution identity ID.

The verifier remains read-only. Identity matching does not grant mutation,
provider, model, database, or project authority.

## Persistence and compatibility

Worker execution and task verification records use version 2 and embed the
execution identity. Checkpoints and journals repeat the identity ID so that
replay cannot silently change actors.

Version 1 worker execution records remain readable for historical continuity.
They cannot satisfy a new independent verification. A legacy step must be
re-executed under a current identity before it can contribute to verified task
completion.

## Failure behavior

KRCN fails closed when an identity is missing, malformed, rebound to another
task, plan, or step, inconsistent with a handler registration, reused between a
worker and verifier, or absent from verification evidence.

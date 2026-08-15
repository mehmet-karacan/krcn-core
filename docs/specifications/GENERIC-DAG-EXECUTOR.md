# Generic DAG Executor

## Purpose

The generic DAG executor runs any authorized KRCN TaskPlan whose executable
steps are workers and verifiers. It reuses the project-scoped runtime queue,
lease, heartbeat, fencing, resource lock, and retry contracts without copying
the research-specific role graph.

Planner activity remains coordinator work and is not placed in the runtime
queue.

## Exact execution plan

Preparation binds:

- the authoritative task plan and task authorization;
- project and Work Item identity, revision, and digest;
- one trusted handler assignment per executable step;
- one agent execution identity per step;
- portable logical resource references;
- maximum concurrency; and
- the current runtime queue state digest.

The queue mutation has its own exact plan and verified dry-run. The execution
plan grants no mutation, provider, model, database, or project authority.

## Scheduling boundary

Queue control operations are serialized because every mutation is bound to the latest queue state digest.
Only leased handler callbacks run concurrently.

At each scheduling cycle the executor:

1. reads completed queue checkpoints;
2. finds steps whose dependencies are complete;
3. excludes ready steps with overlapping logical resources;
4. enqueues and claims the selected bounded batch;
5. renews every lease with a periodic heartbeat;
6. runs callbacks concurrently; and
7. records one digest-bound completion or failure per step.

The executor adds a plan-specific and step-specific claim capability, so a
worker cannot accidentally lease a different plan or step with the same trust
role.

## Identity and result binding

The trusted adapter handler ID, actor digest, and runtime kind must match the
prepared assignment. The opaque owner token digest must match the execution
identity session digest. Worker and verifier owner tokens are distinct.

Verifier actor and assignment digests must differ from every covered worker.
Every adapter result is bound to the task, task plan, step, and execution
identity. The result contains only an evidence digest and grants no authority.

## Recovery

Completed queue checkpoints are not executed again. A new exact execution plan
can resume a partial DAG from those checkpoints. A failed read-only step can use
the queue retry policy. Execute, write, and network failures require explicit
recovery. Active, blocked, or recovery-required steps fail closed.

Queue records persist no handler output, source content, owner token, physical
path, or credential. Domain checkpoints remain the responsibility of the
Execution Coordinator and its worker or verifier handler.

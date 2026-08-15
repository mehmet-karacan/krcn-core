# Measured Loop Contract

## Status

This specification defines the KRCN Core bounded measured-loop record model and adaptive admission contract. The module is transport-neutral and scheduler-neutral. It creates and validates records; it does not start, stop, kill, or resume operating-system processes.

## Safety boundary

A measured loop is an authorized task refinement mechanism, not a new authority source.

- The default effects are exactly `plan`, `read`, and `research`.
- Every `database`, `execute`, `network`, `user-data`, or `write` effect requires a logical approval reference and an existing authorization digest.
- Effect authorization records expose existing authority. They never create or expand it.
- Every plan, iteration, status, cancellation, admission, and morning record sets `grants_authority` to `false`.
- Cancellation is a durable intent record only. It never claims that a process signal was sent or that a process terminated.
- Admission can admit or defer new claims. It preserves active work and never requests a kill.

## Immutable plan

`build_measured_loop_plan` binds a run to the following immutable inputs:

- project, work item, task, task plan, task authorization, and policy digests;
- objective identifier and bounded statement;
- sorted constraint and acceptance references;
- one or more metrics with owner, source, direction, unit, baseline, target, and minimum meaningful delta;
- hard ceilings for rounds, wall time, input tokens, output tokens, cost, attempts, and concurrency;
- independent worker and verifier execution identities;
- allowed effects and their existing approval references;
- the previous terminal run, when present.

The objective has its own digest. The complete plan has a canonical JSON SHA-256 digest. A new run may reference a previous run only when the previous status is terminal and the policy cooldown has elapsed.

## Iteration chain

`create_iteration_record` produces a deterministic, hash-linked iteration record. Each record includes:

- a one-based iteration number and the previous iteration digest;
- canonical UTC start and end timestamps and derived duration;
- worker and verifier execution identity identifiers;
- complete metric observations and deltas from the previous verified value;
- input tokens, output tokens, cost, attempts, and peak concurrency;
- evidence, checkpoint, and verifier evidence digests;
- a verifier result and one of `accept`, `continue`, or `revert`.

An `accept` or `continue` decision requires successful independent verification. `accept` additionally requires every target to be met. `validate_iteration_chain` recomputes digests, metric deltas, identity bindings, ordering, and cumulative budgets. It rejects records after `accept` or `revert`.

Iteration time is also part of the fail-closed binding. An iteration cannot start before `plan.created_at`, end after the immutable wall-time deadline, or overlap the previous verified iteration. A hash-valid imported record outside that window is still invalid.

## Status and stop reasons

`build_measured_loop_status` derives state from the verified plan and iteration chain. It uses these stop reasons:

| Stop reason | Meaning |
|---|---|
| `accept` | All targets were independently verified and accepted. |
| `revert` | The latest verified decision rejects the candidate checkpoint. |
| `continue` | The run remains planned or running within its bounds. |
| `plateau` | The policy plateau window contains no minimum meaningful improvement. |
| `budget` | A hard round, time, token, cost, or attempt ceiling was reached. |
| `cancel` | A matching durable cancellation record exists. |
| `zombie` | No verified activity occurred within the policy zombie interval. |

Zombie status is `recovery-required`. It does not infer that a process is alive or dead. Recovery must verify external runtime state through a separately authorized adapter.

`resume_measured_loop` accepts only a plan, hash-valid iteration chain, and matching persisted status. Terminal runs are returned unchanged. Nonterminal runs are reprojected from the verified records at the new observation time.

Status time is monotonic. A status observation cannot predate the plan or the latest verified iteration. A resume observation cannot predate its persisted status. Reaching the wall-time deadline always projects a terminal `budget` result, including a run with no completed iterations.

## Adaptive admission

`decide_admission` combines the immutable plan ceiling with policy and current pressure evidence:

- CPU pressure;
- RAM pressure;
- provider quota remaining when the provider is required;
- remaining cost headroom;
- recent failure pressure;
- active claims and concurrency capacity.

The result is exactly `admit` or `defer`. Admission never changes an active claim and always emits `active_work_action: preserve` and `kill_requested: false`. Pressure evidence cannot expand a plan ceiling or grant authority.

Admission binds the status start time to `plan.created_at` and requires the admission observation to be at least as recent as the status observation. A status older than the policy zombie interval is deferred with `status-stale`. An observation at or after the immutable wall-time deadline is deferred with `wall-time-budget`. A status that claims to remain nonterminal after its wall-time deadline is rejected as inconsistent.

## Safe projections

Status and morning digest records are safe aggregate projections. They include identifiers, digests, state, stop reason, usage totals, metric values, and a safe next action. They omit prompts, generated output, physical paths, and secrets, with explicit false containment flags.

## Public Python API

The public record constructors and validators in `krcn_core.measured_loop` are:

- `load_measured_loop_policy` and `parse_measured_loop_policy`
- `build_measured_loop_plan` and `parse_measured_loop_plan`
- `create_iteration_record`, `parse_iteration_record`, and `validate_iteration_chain`
- `create_cancellation_record` and `parse_cancellation_record`
- `build_measured_loop_status` and `parse_measured_loop_status`
- `resume_measured_loop`
- `decide_admission` and `parse_admission_decision`
- `build_morning_digest` and `parse_morning_digest`

All parser functions reject unknown fields and invalid canonical digests. The JSON Schemas under `schemas/measured-loop-*.schema.json` provide the corresponding strict transport contracts.

## Integration constraint

This package intentionally does not register commands, routes, repositories, persistence handlers, or schedulers. A later reviewed adapter may persist these records and connect them to the existing authority and execution boundaries. Such an adapter must preserve every digest, approval reference, independent-verifier requirement, and exact-plan gate defined here.

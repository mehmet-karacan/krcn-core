# Request-bound authorization

KRCN does not ask for the same unchanged authority twice. This rule has two separate paths and neither changes ownership policy.

## Routine local operations

Runtime-owned checkpoints, progress, handoffs, evidence and receipts, bounded registered-project observation reconciliation, and derived knowledge/index rebuild or repair remain dry-run and exact-plan bound but do not require user approval. Generic user-data writes cannot label themselves as routine reconciliation. Delete, move and irreversible effects are excluded.

## Explicit persistent local requests

A current explicit user request may replace a second approval prompt only when a trusted host adapter, the human-owned interactive CLI boundary, or the narrow server-parsed `krcn ask` Work Graph create path supplies `initiating-request-evidence`. The application service derives a private authorization bound to:

- session and current user-turn digest;
- client request, operation and project;
- the exact reviewed plan;
- the complete sorted target set and effect-plan digest;
- a short expiry window.

The reviewed operations are Work Graph item mutation, managed client bootstrap, and implementation delivery. Implementation reuse accepts at most 20 create/update effects, rejects `.git`, `.github`, `.krcn`, and every delete, and retains the delivery layer's sandbox-artifact, source-revision and test bindings. Unknown operations fail closed.

Before authoritative mutation, the application atomically writes a `pending` claim under KRCN runtime data containing the evidence identity and complete exact effect plans. Successful apply upgrades it to a `consumed` receipt with the result digest and complete prior service response. An exact, still-current replay with the same evidence returns that response without executing effects again. If authoritative apply succeeds but terminal journaling is interrupted, retry reconciles exact observed target digests and finalizes the receipt without executing effects again. A pending claim with no started effects resumes once; a partial or mismatched state returns machine-readable `recovery-required` with the local repair operation and does not request new authority. Another session, request, operation, project, plan, target/effect set, expired evidence or altered result cannot reuse it.

Raw service arguments and arbitrary subprocesses are not a trusted boundary and cannot mint their own authorization. SDK/MCP/client adapters must inject current-turn evidence through the host-only application-service provider. The reviewed `krcn ask` path is the client-neutral exception: it parses a current explicit create imperative server-side, binds the exact text/session/client/plan/effects, and plans and applies within that request. Its create intent is create-only (`expected_revision=0`); an existing Work Graph identity conflicts and is never overwritten. Without a trusted provider or this narrow path, legacy exact approval remains required.

## Gates preserved

Delete, purge, move, irreversible, bulk, cross-project, unknown, secret, provider, database, Git, deploy and cost-bearing actions retain their dedicated approval or provider gate. `apply=false` never writes. Any stale revision, source identity change, plan mismatch, scope drift or receipt conflict fails closed.

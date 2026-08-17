# Outbound Assurance

## Purpose

Outbound Assurance is the content-free decision layer between an authorized
ProviderRequest and any remote payload transmission. It does not replace the
Provider Gate and never grants provider, network, mutation, or secret access.

## Records

Provider Assurance Profile binds a provider identity to observation and
expiry timestamps, accepted data classifications, retention posture,
training opt-out, regional processing, canary credential evidence, and one
logical evidence digest. It stores no prompt, source, document, credential,
endpoint secret, or physical path.

Outbound Data Decision binds the exact ProviderRequest, payload digest, sorted
data classifications, optional current assurance profile, evaluation time,
verdict, and reason codes. The payload is never persisted in the decision.

Secret Broker Ref identifies a secret through a logical broker reference. It
does not contain the secret value and does not authorize reading it.

## Invariants

- Secret-class remote transmission is always blocked.
- Internal and confidential IP require a current matching assurance profile.
- Confidential IP additionally requires verified training opt-out and regional
  processing controls.
- A current canary credential test is mandatory for assured remote use.
- Data classifications must exactly match the ProviderRequest disclosure.
- A remote decision requires an already verified ProviderAuthorization.
- Local-only deterministic processing is explicitly marked allowed-local and
  does not imply remote authority.
- Unknown fields, noncanonical timestamps, path-shaped refs, digest tampering,
  stale assurance, provider mismatch, and category mismatch fail closed.

## Persistence boundary

These records are strict contracts. This phase does not introduce automatic
profile collection or remote calls. A future persistence adapter must use
existing ownership and exact mutation authorization and must never store raw
canary material.


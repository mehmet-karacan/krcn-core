# Worktree Sandbox

## Purpose

The Worktree Sandbox binds a mutating agent step to one exact Git HEAD and
tree, one Validation Gate, one Effect Claim, one runtime MutationPlan, one
platform enforcement profile, and one changed-path allowlist.

## Host enforcement

A host profile is executable only when it proves detached worktree support,
path isolation, environment allowlisting, network default deny, commit and
push blocking, and junction guarding. A missing capability blocks execution;
the system does not silently fall back to an ordinary subprocess.

Windows, Linux, and macOS use the same public contract. Platform-specific
adapters may implement isolation differently, but they may not weaken the
required flags.

## Detached worktree lifecycle

Creation requires the exact runtime MutationAuthorization and rechecks source
HEAD and tree immediately before `git worktree add --detach`. The physical
sandbox path remains process-local and is not part of the public plan.

The core adapter does not expose arbitrary command execution. Agent execution
belongs to a separately reviewed host adapter that enforces the declared
executable, environment, network, timeout, and output boundaries.

## Patch artifact

Patch collection rejects source commit drift, traversal, absolute paths,
Windows drive paths, UNC paths, symlinks, junctions, resolved path escapes,
case collisions, and changes outside the allowlist. Untracked files are added
to the sandbox index as intent-to-add so the binary patch includes them.

The public artifact stores changed relative paths, content digests, patch
digest, source identity, Validation Gate, Effect Claim, Effect Receipt, and
verifier evidence digest. Patch bytes remain an ephemeral artifact and are
bounded by the exact plan. Commit and push flags are always false.

## Cleanup

Cleanup accepts only a physical worktree whose final directory name equals the
exact sandbox plan id and delegates to `git worktree remove --force`. Cleanup
does not erase append-only gate, claim, receipt, verifier, or patch evidence.


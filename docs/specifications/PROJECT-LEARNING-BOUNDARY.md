# Natural-language project learning boundary

## Purpose

KRCN accepts a local project directory as the only required project-specific input. A user may provide the directory alone or express an intent such as learn, recognize, register, onboard, or integrate this project. The shared service derives reversible metadata and prepares one exact plan for read-only onboarding and initial discovery.

## Safe inference

KRCN may infer the display name from reviewed project markers or the directory name. It derives portable workspace, project, and binding identifiers from that name. Local registry collisions are resolved with a deterministic numeric suffix. These values are shown in the dry-run summary before mutation.

Safe inference does not include policy, write capability, remote provider, repository ownership, deployment target, database authority, or secret configuration. Those remain explicit user-owned inputs.

## Source rule

- The selected directory must exist, be absolute, and remain outside the KRCN user home.
- Project markers and permitted files are read through the existing local discovery policy.
- Project content is not copied, moved, uploaded, rewritten, or marked.
- The default binding is read-only and has only read and metadata capabilities.
- Symbolic links and policy-blocked content remain outside discovery.

## Mutation and approval

Natural language expresses intent but does not bypass the mutation gate. The service first returns an exact plan containing inferred identities, record effects, file count, technologies, and verification requirements. One explicit approval for that exact plan may authorize workspace, project, source binding, and derived source-state records.

## Client behavior

CLI, SDK, MCP, plugins, Codex, Claude, and future clients call the same `project.learn` operation. Client wording may differ, but intent recognition, path validation, inference, planning, approval, application, and verification remain in the shared core.


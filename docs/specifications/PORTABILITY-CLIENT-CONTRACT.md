# Portability client contract

## Shared entrypoint

CLI, SDK, MCP, plugins, Codex, Claude, and future clients use `create_application_service` from `krcn_core.application`. A client may pass an explicit user-home path. Otherwise the factory resolves `KRCN_HOME` and then the operating-system default.

Client adapters do not implement backup, restore, migration, or rebind rules. They submit the same transport-neutral `ServiceRequest` operations:

- `project.rebind`
- `portability.backup`
- `portability.restore`
- `portability.migrate-repo-local`
- `portability.migrate-project-home`
- `portability.restore-project-home`
- `portability.merge-project-home`

Project-home migration always creates and verifies a secret-safe backup before restoring an empty approved target. The original home remains untouched. Clean-clone recovery restores an archive that already contains a valid project-home manifest and applies the same local Git exclusion boundary before making the restored home active.

Project-home merge targets an existing shared home. It creates and verifies separate secret-safe backups of source and target, fails on differing records with the same relative path, preserves every pre-existing target file, copies only approved user-data record areas, and leaves the source unchanged. Runtime, derived, local-data, project-home manifests, and secret values are excluded.

## Platform rule

Windows and macOS use platform-appropriate physical defaults. Portable archives use only forward-slash relative paths, the same layout version, readable JSON documents, and the same canonical SHA-256 identity rules. Physical user-home and source paths do not contribute to the portable backup identity after source locators are transformed to `unbound` dependencies.

## Security parity

The `client_kind` field identifies the caller for traceability. It cannot change the plan, capability, policy, ownership, approval, no-copy, secret, or verification decision. No client receives a physical source locator in a public response.

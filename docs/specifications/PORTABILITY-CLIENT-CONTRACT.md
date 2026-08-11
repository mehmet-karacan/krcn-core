# Portability client contract

## Shared entrypoint

CLI, SDK, MCP, plugins, Codex, Claude, and future clients use `create_application_service` from `krcn_core.application`. A client may pass an explicit user-home path. Otherwise the factory resolves `KRCN_HOME` and then the operating-system default.

Client adapters do not implement backup, restore, migration, or rebind rules. They submit the same transport-neutral `ServiceRequest` operations:

- `project.rebind`
- `portability.backup`
- `portability.restore`
- `portability.migrate-repo-local`

## Platform rule

Windows and macOS use platform-appropriate physical defaults. Portable archives use only forward-slash relative paths, the same layout version, the same canonical JSON representation, and the same SHA-256 identity rules. Physical user-home and source paths do not contribute to the portable backup identity after source locators are transformed to `unbound` dependencies.

## Security parity

The `client_kind` field identifies the caller for traceability. It cannot change the plan, capability, policy, ownership, approval, no-copy, secret, or verification decision. No client receives a physical source locator in a public response.


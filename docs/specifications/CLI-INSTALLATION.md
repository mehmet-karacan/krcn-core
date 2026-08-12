# CLI installation boundary

## Purpose

The `krcn` command is the client-neutral local entrypoint for PowerShell, Command Prompt, Git Bash, AI clients, plugins, and future adapters. Installation exposes the existing console entrypoint; it does not grant capabilities or bypass the application service.

## Separation of locations

Three locations have different responsibilities:

| Location | Responsibility | Resolution |
| --- | --- | --- |
| KRCN Core repository | Versioned code, schemas, policies, and technical context | Current KRCN Core tree, explicit `--repo`, or `KRCN_CORE_HOME` |
| CLI installation | Python package and the `krcn` executable | Active Python environment and its scripts directory |
| KRCN user home | User data, runtime state, derived data, and secret references | Explicit `--data-root`, `KRCN_HOME`, project-home resolution, or platform default |

`KRCN_CORE_HOME` and `KRCN_HOME` are intentionally separate. Installing or updating the CLI may set the former to the approved repository clone. It must never create, move, merge, or select the latter implicitly.

## Windows bootstrap

`tools/install_cli.py` is the supported repository bootstrap for Windows. It can be started from PowerShell, Command Prompt, or Git Bash without depending on the PowerShell script execution policy. It:

1. Resolves the current KRCN Core clone without storing its physical path in Git.
2. Requires Python 3.11 or newer.
3. builds and verifies the dependency-free wheel without network access;
4. installs or replaces the package in the selected Python environment;
5. records the clone in the user-level `KRCN_CORE_HOME` environment value;
6. adds the Python scripts directory to the user PATH only when missing;
7. verifies the installed command from outside the repository.

`--plan-only` reports the resolved installation effects without changing the package, PATH, or environment values.

## Update contract

A Git pull changes the checked-out source but does not silently replace an installed executable. After an approved core update, rerunning the installer rebuilds and reinstalls the CLI from the exact checked-out revision. The installed CLI resolves schemas, policies, and repository context from the approved `KRCN_CORE_HOME` clone.

Clients may continue using `python tools/krcn.py` before installation or while repairing an installation.

## Data and security guarantees

- Installation does not inspect or copy external project sources.
- Installation does not set or migrate `KRCN_HOME`.
- Installation does not send data to a provider or package index.
- Installation does not copy tokens, credentials, or secret values.
- Installation does not stage or commit local data.
- User-home selection and migration remain separate exact-plan operations with their existing approval rules.

## Recovery and removal

Reinstalling the same or a later approved revision is the normal repair path. Removing the Python package or the `krcn` PATH entry must not remove `KRCN_HOME`, external project bindings, backups, or repository content. Changing the repository clone requires rerunning the installer from the new approved clone so `KRCN_CORE_HOME` is updated deliberately.

## Acceptance criteria

- `krcn context --validate-only` succeeds from a directory outside the repository.
- `krcn doctor` resolves the approved core clone without requiring `--repo`.
- The command uses the same application service and policy gates as direct repository execution.
- The configured user data root remains unchanged during installation and update.

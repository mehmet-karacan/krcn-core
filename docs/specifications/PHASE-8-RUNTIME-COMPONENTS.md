# Phase 8 runtime component boundary

KRCN runtime components are explicit, capability-bound callbacks. The core does not scan the host, installed plugins, Python modules, CLIs, models, or personal AI skills to discover executable authority.

## Component model

The shared registry supports five execution roles:

1. A skill validates or transforms a declared input.
2. An adapter performs one declared operation against one source kind.
3. A secret provider resolves an explicit reference without exposing its value.
4. A worker invokes an already authorized operation.
5. A verifier independently validates the produced evidence.

Each runtime component names exact capability records, required capabilities, and possible side effects. Registration fails when the declared kind or side effects exceed those records. A component selection never grants policy, mutation, provider, or source authority by itself.

Repository runtime skills are executable product components. Personal Codex or another AI tool's instruction skills may explain how to call the product, but they are not silently loaded as trusted runtime code. Any client uses the same application service and therefore the same policy and capability decisions.

## SQLite reference flow

The `sqlite-read-only` reference adapter proves the complete local chain:

1. The integration and source binding must be active, matching, and read-only.
2. Both records must name the same explicit user policy.
3. The database-query skill rejects anything outside the allowed SQL statement class.
4. The adapter gate requires `read` and `execute` capabilities and an effective allow decision.
5. The local provider resolves only `secret://` references beneath the configured secret root.
6. The connection secret must be a SQLite `file:` URI containing `mode=ro`.
7. SQLite `query_only` mode is enabled before execution.
8. The worker applies the declared row limit and the verifier recomputes the result digest.

Public output contains column names, row count, policy evidence, selection evidence, and digests. It contains no rows, connection URI, secret value, database path, mutation, or network effect.

## Secret file convention

For a project home at `<project>/.krcn`, `secret://database/reporting` resolves locally to `<project>/.krcn/secrets/database/reporting.secret`. Secret files are ignored local data. They are excluded from repository commits and portable backups. Creating, rotating, and restoring secret values remains a user or approved provider action.

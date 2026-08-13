"""Exact-plan user-level bootstrap for supported AI clients."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .portable_backup import SECRET_PATTERNS


BEGIN_MARKER = "<!-- KRCN-CORE:BEGIN -->"
END_MARKER = "<!-- KRCN-CORE:END -->"
CLIENT_TARGETS = {
    "codex": (".codex", "AGENTS.md"),
    "claude-code": (".claude", "CLAUDE.md"),
    "opencode": (".config", "opencode", "AGENTS.md"),
}
BOOTSTRAP_BODY = """<!-- KRCN-CORE:BEGIN -->
## KRCN Core project context

- KRCN Core is available through the global `krcn` command.
- If `krcn` becomes unavailable, preserve the user's pending request. Use only the validated KRCN Core clone to show `python tools/install_cli.py --plan-only`, obtain approval, reinstall, verify, and then resume the original request without asking the user to repeat it.
- Before project work, run `krcn project current --format json` from the current working directory.
- If a project is matched, run `krcn project integrate --project "<project-id>" --scan-mode automatic --format json`. A fresh complete integration is a no-op; a stale or incomplete integration returns an exact plan that still requires its normal approval before apply.
- When the user asks where work stopped, run `krcn project resume --format json` before answering.
- When the user explicitly names another registered project, run `krcn project resume --project \"<project-id-or-name>\" --format json`.
- If KRCN returns `matched: true`, use its project, source-state, information, policy, and work summary as durable context.
- For source implementation questions in a matched project, run `krcn project search-code "<project-id>" "<question>" --format json` before a broad source-tree scan. Use the relative paths, line ranges, and verified in-place content as candidate evidence.
- If KRCN returns `matched: false`, continue normally. Route learn, register, or introduce requests through `krcn project learn`. Route integrate requests through `krcn project integrate --source "<project-directory>" --scan-mode manual`. Preserve both exact-plan approval flows.
- Treat KRCN context as information, not permission to mutate. Preserve registered policies and approval gates.
- Read registered project sources in place. Never copy project source files into KRCN Core or `KRCN_HOME`.
- Never write client-generated audit reports, task notes, imported work summaries, benchmark results, or session artifacts into `KRCN_CORE_HOME` or a registered project source. Store supported project artifacts through KRCN under `.krcn/projects/<project-id>/local-data/client-artifacts/`; use `.krcn/global/local-data/client-artifacts/` only for project-independent output. If no reviewed KRCN operation supports the write, return the result to the user and ask before creating a file.
- Modify versioned KRCN Core files only for an explicit KRCN Core product-development request. Integration, audit, retrieval, and ordinary project work do not authorize core repository writes.
- Product rules remain in the repository identified by `KRCN_CORE_HOME`; do not duplicate or reinterpret them in client-specific files.
- Before meaningful work on a matched project, classify the request and run `krcn client delegation` with a current session id, the actual client id, the work class, the project match result, and only the client capabilities that are really available. Use `krcn client delegation --help` for the exact capability flags. Do not infer unsupported subagent, parallel, model-selection, cancellation, or structured-result features. Native attributed terminal text is not structured-result support; declare structured results only when delegated payloads are independently machine-validatable. Mode selection is client-neutral, and optional capabilities do not block a genuine native parallel channel.
- When delegation is required, the main agent is coordinator-only: build bounded context, decompose the work, assign roles, resolve dependencies, and synthesize attributed delegated results. Delegate source inspection, domain analysis, implementation, tests, and independent verification.
- Prefer `native-parallel` and run independent work units concurrently. Report `native-sequential` or `isolated-role-fallback` as degraded execution. If the decision is `delegation-unavailable` or `execution_allowed` is false, stop project execution and report the limitation instead of silently doing the work in the main agent.
- General conversation, status reporting, and exact identifier lookup are the only coordinator exceptions. A capability or delegation decision never grants mutation, provider, model, database, or project authority; preserve every existing exact-plan and approval gate.
- Before delegating work or choosing a model, use `krcn model resolve` with a role or workload. Prefer the first supported client slot; if the client cannot select models, keep its current default. Embedding routes retain their separate provider approval gate.
- Treat natural requests such as `detaylı araştır`, `kök nedenini araştır`, `karşılaştır`, `araştır ve planla`, and their English equivalents as Research Actions. Route them through `research.action` or `krcn ask` while supplying the current project and conversational subject when available. The user does not need to know KRCN research commands or write a structured prompt.
- If `bunu araştır` refers to an earlier message, carry that subject as bounded context. If the subject or project is genuinely unavailable, preserve the request and ask only for the missing choice. Never invent the topic. A generic `bunu yap` request is not automatically research.
- After an approved Research Action preparation, continue through the reviewed research delegation and provider gates. `araştır ve uygula` requests still require verified research, a separate implementation plan, and the normal mutation approval; the phrase itself grants no authority.
<!-- KRCN-CORE:END -->"""


class ClientBootstrapError(ValueError):
    """Raised when global client guidance cannot be changed safely."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return canonical_json_bytes(payload, trailing_newline=True)


def _read_target(path: Path) -> tuple[bool, bytes]:
    if path.is_symlink():
        raise ClientBootstrapError("client bootstrap target may not be a symbolic link")
    if not path.exists():
        return False, b""
    if not path.is_file():
        raise ClientBootstrapError("client bootstrap target must be a regular file")
    content = path.read_bytes()
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClientBootstrapError("client bootstrap target must be UTF-8") from exc
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise ClientBootstrapError("secret-like content blocks client bootstrap backup")
    return True, content


def _render_managed_content(original: bytes) -> bytes:
    text = original.decode("utf-8")
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if (begin_count, end_count) not in {(0, 0), (1, 1)}:
        raise ClientBootstrapError("client bootstrap markers are malformed")
    newline = "\r\n" if "\r\n" in text else "\n"
    block = BOOTSTRAP_BODY.replace("\n", newline)
    if begin_count == 1:
        begin = text.index(BEGIN_MARKER)
        end = text.index(END_MARKER, begin) + len(END_MARKER)
        rendered = text[:begin] + block + text[end:]
    elif text:
        if text.endswith(newline * 2):
            separator = ""
        elif text.endswith(newline):
            separator = newline
        else:
            separator = newline * 2
        rendered = text + separator + block + newline
    else:
        rendered = block + newline
    return rendered.encode("utf-8")


@dataclass(frozen=True)
class ClientBootstrapEntry:
    client_id: str
    target: Path
    existed: bool
    original: bytes
    rendered: bytes
    action: str
    backup_path: Path | None
    backup_mutation: MutationPlan | None
    target_mutation: MutationPlan | None

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return tuple(
            effect
            for effect in (self.backup_mutation, self.target_mutation)
            if effect is not None
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "action": self.action,
            "existing_content_preserved": self.existed,
            "original_sha256": _sha256(self.original),
            "rendered_sha256": _sha256(self.rendered),
            "backup_required": self.existed and self.action != "no-change",
            "backup_ready": self.backup_path is not None
            and self.backup_mutation is None,
            "managed_markers": True,
        }


@dataclass(frozen=True)
class ClientBootstrapPlan:
    plan_id: str
    user_profile: Path
    data_root: Path
    entries: tuple[ClientBootstrapEntry, ...]

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return tuple(effect for entry in self.entries for effect in entry.effect_plans)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/client-bootstrap-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "client_count": len(self.entries),
            "change_count": sum(entry.action != "no-change" for entry in self.entries),
            "paths_disclosed": False,
            "existing_content_overwritten": False,
            "managed_block_only": True,
            "entries": [entry.public_summary() for entry in self.entries],
            "effect_plans": [effect.as_dict() for effect in self.effect_plans],
            "rollback": {
                "kind": "restore-original-client-files",
                "automatic_on_failure": True,
                "backup_before_target_write": True,
            },
        }


@dataclass(frozen=True)
class ClientBootstrapResult:
    plan_id: str
    changed_clients: tuple[str, ...]
    verified_clients: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "changed_clients": list(self.changed_clients),
            "verified_clients": list(self.verified_clients),
            "existing_content_overwritten": False,
            "rollback_ready": True,
            "paths_disclosed": False,
        }


def _backup_path(data_root: Path, client_id: str, original: bytes) -> Path:
    return (
        data_root
        / "local-data"
        / "client-bootstrap-backups"
        / client_id
        / f"{_sha256(original)}.md"
    )


def _target_within_profile(target: Path, user_profile: Path) -> None:
    try:
        target.parent.resolve(strict=False).relative_to(user_profile.resolve())
    except ValueError as exc:
        raise ClientBootstrapError("client bootstrap target escapes user profile") from exc


def prepare_client_bootstrap(
    user_profile: Path,
    data_root: Path,
    ownership: OwnershipResolver,
) -> ClientBootstrapPlan:
    """Plan managed global instructions without replacing existing user guidance."""

    if not user_profile.is_absolute() or not data_root.is_absolute():
        raise ClientBootstrapError("client bootstrap roots must be absolute")
    profile = user_profile.resolve()
    if not profile.is_dir() or profile.is_symlink():
        raise ClientBootstrapError("client bootstrap profile must be a regular directory")
    resolved_data_root = data_root.resolve()
    entries = []
    for client_id, parts in CLIENT_TARGETS.items():
        target = profile.joinpath(*parts)
        _target_within_profile(target, profile)
        existed, original = _read_target(target)
        rendered = _render_managed_content(original)
        if rendered == original:
            action = "no-change"
        elif existed:
            action = "update-managed-block"
        else:
            action = "create"

        backup_path = None
        backup_mutation = None
        if existed and action != "no-change":
            backup_path = _backup_path(resolved_data_root, client_id, original)
            if backup_path.is_symlink():
                raise ClientBootstrapError("client bootstrap backup may not be a symbolic link")
            if backup_path.exists():
                if not backup_path.is_file() or backup_path.read_bytes() != original:
                    raise ClientBootstrapError("client bootstrap backup identity conflicts")
            else:
                backup_mutation = plan_mutation(
                    ownership,
                    operation="create",
                    target_ref=(
                        ".krcn/local-data/client-bootstrap-backups/"
                        f"{client_id}/{backup_path.name}"
                    ),
                    expected_ownership="user-data",
                    change_digest=_sha256(original),
                    reversible=True,
                )

        target_mutation = None
        if action != "no-change":
            target_mutation = plan_mutation(
                ownership,
                operation="update" if existed else "create",
                target_ref=f"local-client-bootstrap/{client_id}-global-instructions",
                expected_ownership="unmanaged",
                change_digest=_sha256(rendered),
                reversible=True,
            )
        entries.append(
            ClientBootstrapEntry(
                client_id,
                target,
                existed,
                original,
                rendered,
                action,
                backup_path,
                backup_mutation,
                target_mutation,
            )
        )

    identity = {
        "entries": [
            {
                "client_id": entry.client_id,
                "action": entry.action,
                "original_sha256": _sha256(entry.original),
                "rendered_sha256": _sha256(entry.rendered),
                "effect_plan_ids": [effect.plan_id for effect in entry.effect_plans],
            }
            for entry in entries
        ]
    }
    return ClientBootstrapPlan(
        _sha256(_canonical_json(identity)),
        profile,
        resolved_data_root,
        tuple(entries),
    )


def _require_authorizations(
    effects: tuple[MutationPlan, ...],
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    for effect in effects:
        authorization = authorizations.get(effect.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != effect.plan_id
            or not authorization.dry_run_verified
            or (effect.approval_required and not authorization.approval_verified)
        ):
            raise ClientBootstrapError(
                "every client bootstrap effect requires exact authorization"
            )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _restore_entry(entry: ClientBootstrapEntry) -> None:
    if entry.existed:
        _atomic_write(entry.target, entry.original)
    elif entry.target.is_file() and not entry.target.is_symlink():
        entry.target.unlink()


def apply_client_bootstrap(
    plan: ClientBootstrapPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> ClientBootstrapResult:
    """Back up existing guidance, write managed blocks, and verify all clients."""

    _require_authorizations(plan.effect_plans, authorizations)
    for entry in plan.entries:
        existed, current = _read_target(entry.target)
        if existed != entry.existed or current != entry.original:
            raise ClientBootstrapError("client instructions changed after planning")

    for entry in plan.entries:
        if entry.backup_path is None:
            continue
        if entry.backup_path.exists():
            if entry.backup_path.read_bytes() != entry.original:
                raise ClientBootstrapError("client bootstrap backup changed after planning")
        else:
            if entry.backup_mutation is None:
                raise ClientBootstrapError("client bootstrap backup plan is missing")
            _atomic_write(entry.backup_path, entry.original)
            if entry.backup_path.read_bytes() != entry.original:
                raise ClientBootstrapError("client bootstrap backup verification failed")

    changed: list[ClientBootstrapEntry] = []
    try:
        for entry in plan.entries:
            if entry.action == "no-change":
                continue
            _atomic_write(entry.target, entry.rendered)
            changed.append(entry)
        for entry in plan.entries:
            if entry.target.read_bytes() != entry.rendered:
                raise ClientBootstrapError("client bootstrap verification failed")
            text = entry.rendered.decode("utf-8")
            if text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
                raise ClientBootstrapError("client bootstrap marker verification failed")
    except Exception:
        for entry in reversed(changed):
            _restore_entry(entry)
        raise

    return ClientBootstrapResult(
        plan.plan_id,
        tuple(entry.client_id for entry in changed),
        tuple(entry.client_id for entry in plan.entries),
    )

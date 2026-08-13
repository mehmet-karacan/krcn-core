"""Bounded, provider-neutral CLI execution for research roles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable, Mapping, Protocol, Sequence

from .foundation import load_json
from .information_records import canonical_json
from .provider_gate import ProviderAuthorization


REQUEST_SCHEMA = "schemas/research-execution-request.schema.json"
RESULT_SCHEMA = "schemas/research-execution-result.schema.json"
OUTPUT_CONTRACT = "research-agent-result-v1"
AGENT_OUTPUT_SCHEMA = "schemas/research-agent-output.schema.json"
SHA256 = re.compile(r"^[a-f0-9]{64}$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SESSION_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
PORTABLE_EXECUTABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?:^|[\s'\"`(])(?:[a-z]:[\\/]|\\\\)[^\s'\"`)]*")
POSIX_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s'\"`(])/(?!/)(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"
)
SECRET_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
)

_EXPECTED_CLIENTS = {
    "opencode": {
        "execution_mode": "native-cli",
        "optional": False,
        "base_argv": (
            "run", "--format", "json", "--pure", "--agent",
            "krcn-research-read-only",
        ),
        "model_argv": ("--model", "{model_ref}"),
        "output_format": "json-or-jsonl",
    },
    "codex-cli": {
        "execution_mode": "native-cli",
        "optional": False,
        "base_argv": (
            "exec", "--json", "--ephemeral", "--sandbox", "read-only",
            "--ignore-user-config", "--ignore-rules",
        ),
        "model_argv": ("--model", "{model_ref}"),
        "output_format": "json-or-jsonl",
    },
    "claude-cli": {
        "execution_mode": "native-cli",
        "optional": False,
        "base_argv": (
            "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--safe-mode", "--permission-mode", "plan", "--tools", "Read,Glob,Grep",
            "--strict-mcp-config", "--mcp-config", "{}", "--disable-slash-commands",
        ),
        "model_argv": ("--model", "{model_ref}"),
        "output_format": "json-or-jsonl",
    },
    "gemini": {
        "execution_mode": "operator-mediated-only",
        "optional": True,
        "base_argv": (),
        "model_argv": (),
        "output_format": "none",
    },
}

OPENCODE_READ_ONLY_CONFIG = json.dumps(
    {
        "agent": {
            "krcn-research-read-only": {
                "mode": "primary",
                "permission": {
                    "*": "deny",
                    "read": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "list": "allow",
                    "lsp": "allow",
                    "edit": "deny",
                    "bash": "deny",
                    "task": "deny",
                    "webfetch": "deny",
                    "websearch": "deny",
                    "skill": "deny",
                    "external_directory": "deny",
                },
            }
        }
    },
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
)


class ResearchExecutionError(ValueError):
    """Raised when a research execution request is unsafe or inconsistent."""


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_text(value: str) -> str:
    return _digest_bytes(value.encode("utf-8"))


def _digest_payload(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _platform_key(platform_name: str | None) -> str:
    if platform_name is None:
        return "windows" if os.name == "nt" else "posix"
    if platform_name not in {"windows", "posix"}:
        raise ResearchExecutionError("research execution platform is invalid")
    return platform_name


def _executable_name(value: str) -> str:
    if "\\" in value or re.match(r"^[A-Za-z]:", value):
        return PureWindowsPath(value).name.lower()
    return Path(value).name.lower()


def _portable_text(value: object, label: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > maximum
        or CONTROL_CHARACTER.search(value)
    ):
        raise ResearchExecutionError(f"{label} is invalid")
    return value


def _reject_sensitive_text(value: str, label: str) -> None:
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise ResearchExecutionError(f"{label} contains a credential value")
    if WINDOWS_ABSOLUTE_PATH.search(value) or POSIX_ABSOLUTE_PATH.search(value):
        raise ResearchExecutionError(f"{label} contains a physical machine path")


@dataclass(frozen=True)
class ResearchClientExecutionPolicy:
    client_id: str
    execution_mode: str
    optional: bool
    default_executable_refs: Mapping[str, str]
    allowed_executable_names: tuple[str, ...]
    base_argv: tuple[str, ...]
    model_argv: tuple[str, ...]
    output_format: str


@dataclass(frozen=True)
class ResearchExecutionPolicy:
    policy_revision: int
    clients: Mapping[str, ResearchClientExecutionPolicy]
    default_timeout_seconds: int
    maximum_timeout_seconds: int
    maximum_prompt_bytes: int
    maximum_stdout_bytes: int
    maximum_stderr_bytes: int
    environment_allowlist: tuple[str, ...]
    blocked_executable_names: tuple[str, ...]
    policy_digest: str


def load_research_execution_policy(repo_root: Path) -> ResearchExecutionPolicy:
    payload = load_json(repo_root / "config" / "research-execution.json")
    expected = {
        "schema_ref", "schema_version", "policy_revision", "clients", "limits",
        "environment_allowlist", "blocked_executable_names", "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ResearchExecutionError("research execution policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/research-execution-policy.schema.json"
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("policy_revision"), int)
        or isinstance(payload.get("policy_revision"), bool)
        or payload["policy_revision"] < 1
    ):
        raise ResearchExecutionError("research execution policy schema is invalid")
    if payload.get("invariants") != {
        "implicit_host_scan": False,
        "shell_string_execution": False,
        "prompt_via_stdin": True,
        "provider_authority_granted": False,
        "credential_values_persisted": False,
        "physical_paths_returned": False,
        "gemini_required": False,
    }:
        raise ResearchExecutionError("research execution policy invariants are invalid")
    raw_clients = payload.get("clients")
    if not isinstance(raw_clients, list) or len(raw_clients) != len(_EXPECTED_CLIENTS):
        raise ResearchExecutionError("research execution clients are invalid")
    clients: dict[str, ResearchClientExecutionPolicy] = {}
    client_fields = {
        "client_id", "execution_mode", "optional", "default_executable_refs",
        "allowed_executable_names", "base_argv", "model_argv", "output_format",
    }
    for raw in raw_clients:
        if not isinstance(raw, dict) or set(raw) != client_fields:
            raise ResearchExecutionError("research execution client fields are invalid")
        client_id = raw.get("client_id")
        if client_id not in _EXPECTED_CLIENTS or client_id in clients:
            raise ResearchExecutionError("research execution client id is invalid")
        expected_client = _EXPECTED_CLIENTS[str(client_id)]
        if any(raw.get(key) != value for key, value in (
            ("execution_mode", expected_client["execution_mode"]),
            ("optional", expected_client["optional"]),
            ("output_format", expected_client["output_format"]),
        )):
            raise ResearchExecutionError("research execution client contract is invalid")
        if tuple(raw.get("base_argv", ())) != expected_client["base_argv"]:
            raise ResearchExecutionError("research execution base argv is invalid")
        if tuple(raw.get("model_argv", ())) != expected_client["model_argv"]:
            raise ResearchExecutionError("research execution model argv is invalid")
        defaults = raw.get("default_executable_refs")
        names = raw.get("allowed_executable_names")
        if (
            not isinstance(defaults, dict)
            or set(defaults) - {"windows", "posix"}
            or any(not isinstance(key, str) or not key for key in defaults.values())
            or not isinstance(names, list)
            or len(names) != len(set(names))
            or any(not isinstance(name, str) or not PORTABLE_EXECUTABLE.fullmatch(name) for name in names)
        ):
            raise ResearchExecutionError("research execution executable references are invalid")
        if str(client_id) == "gemini":
            if defaults or names:
                raise ResearchExecutionError("Gemini must remain operator mediated")
        elif set(defaults) != {"windows", "posix"}:
            raise ResearchExecutionError("native research executable defaults are incomplete")
        clients[str(client_id)] = ResearchClientExecutionPolicy(
            str(client_id), str(raw["execution_mode"]), bool(raw["optional"]),
            dict(defaults), tuple(str(name).lower() for name in names),
            tuple(raw["base_argv"]), tuple(raw["model_argv"]), str(raw["output_format"]),
        )
    if set(clients) != set(_EXPECTED_CLIENTS):
        raise ResearchExecutionError("research execution clients are incomplete")
    limits = payload.get("limits")
    limit_fields = {
        "default_timeout_seconds", "maximum_timeout_seconds", "maximum_prompt_bytes",
        "maximum_stdout_bytes", "maximum_stderr_bytes",
    }
    if not isinstance(limits, dict) or set(limits) != limit_fields:
        raise ResearchExecutionError("research execution limits are invalid")
    if any(not isinstance(limits[key], int) or isinstance(limits[key], bool) for key in limit_fields):
        raise ResearchExecutionError("research execution limits are invalid")
    if not (
        1 <= limits["default_timeout_seconds"] <= limits["maximum_timeout_seconds"] <= 3600
        and 1024 <= limits["maximum_prompt_bytes"] <= 16 * 1024 * 1024
        and 1024 <= limits["maximum_stdout_bytes"] <= 16 * 1024 * 1024
        and 1024 <= limits["maximum_stderr_bytes"] <= 4 * 1024 * 1024
    ):
        raise ResearchExecutionError("research execution limits are outside safe bounds")
    allowlist = payload.get("environment_allowlist")
    blocked = payload.get("blocked_executable_names")
    if (
        not isinstance(allowlist, list)
        or len(allowlist) != len(set(allowlist))
        or any(not isinstance(item, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", item) for item in allowlist)
        or any("TOKEN" in item or "KEY" in item or "SECRET" in item for item in allowlist)
        or not isinstance(blocked, list)
        or len(blocked) != len(set(blocked))
        or any(not isinstance(item, str) or not item for item in blocked)
    ):
        raise ResearchExecutionError("research execution environment policy is invalid")
    return ResearchExecutionPolicy(
        int(payload["policy_revision"]), clients,
        int(limits["default_timeout_seconds"]), int(limits["maximum_timeout_seconds"]),
        int(limits["maximum_prompt_bytes"]), int(limits["maximum_stdout_bytes"]),
        int(limits["maximum_stderr_bytes"]), tuple(allowlist),
        tuple(str(item).lower() for item in blocked), _digest_payload(payload),
    )


@dataclass(frozen=True)
class ResearchExecutionPlan:
    client_id: str
    execution_mode: str
    optional: bool
    executable_ref: str | None
    cwd: Path
    cwd_boundary: Path
    provider: str
    provider_request_id: str
    session_id: str
    model_ref: str | None
    argv_tail: tuple[str, ...]
    output_format: str
    output_contract: str
    timeout_seconds: int
    max_prompt_bytes: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    environment_allowlist: tuple[str, ...]
    allowed_executable_names: tuple[str, ...]
    blocked_executable_names: tuple[str, ...]
    platform_name: str
    environment_overrides: Mapping[str, str]
    status: str

    @property
    def executable_ref_sha256(self) -> str:
        return _digest_text(self.executable_ref or "operator-mediated")

    @property
    def cwd_sha256(self) -> str:
        return _digest_text(str(self.cwd))

    def public_summary(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "execution_mode": self.execution_mode,
            "optional": self.optional,
            "status": self.status,
            "executable_ref_sha256": self.executable_ref_sha256,
            "cwd_sha256": self.cwd_sha256,
            "provider": self.provider,
            "provider_request_id": self.provider_request_id,
            "session_id": self.session_id,
            "model_ref": self.model_ref,
            "output_contract": self.output_contract,
            "environment_override_sha256": _digest_payload(self.environment_overrides),
            "provider_authority_granted": False,
            "physical_paths_included": False,
            "credential_values_included": False,
        }


def _resolved_directory(value: object, label: str) -> Path:
    text = _portable_text(value, label, maximum=4096)
    path = Path(text)
    if not path.is_absolute():
        raise ResearchExecutionError(f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ResearchExecutionError(f"{label} is unavailable") from exc
    if not resolved.is_dir():
        raise ResearchExecutionError(f"{label} must be a directory")
    return resolved


def _validate_executable_ref(
    value: str,
    client: ResearchClientExecutionPolicy,
    blocked: Sequence[str],
    platform_name: str,
) -> str:
    value = _portable_text(value, "research executable reference", maximum=4096)
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise ResearchExecutionError("research executable reference is invalid")
    name = _executable_name(value)
    if name in blocked or name not in client.allowed_executable_names:
        raise ResearchExecutionError("research executable is not allowed for the client")
    path = Path(value)
    if not path.is_absolute() and value != name and value.lower() != name:
        raise ResearchExecutionError("research executable must be an absolute path or portable name")
    suffix = PureWindowsPath(value).suffix.lower() if platform_name == "windows" else Path(value).suffix.lower()
    if platform_name == "windows" and suffix not in {"", ".cmd", ".exe"}:
        raise ResearchExecutionError("Windows research executable must be .cmd or .exe")
    if platform_name == "posix" and suffix in {".cmd", ".exe", ".ps1", ".bat"}:
        raise ResearchExecutionError("research executable does not match the platform")
    return value


def resolve_research_execution(
    policy: ResearchExecutionPolicy,
    request: Mapping[str, object],
    *,
    platform_name: str | None = None,
) -> ResearchExecutionPlan:
    expected = {
        "schema_ref", "schema_version", "client_id", "executable_ref", "cwd",
        "cwd_boundary", "model_ref", "provider", "provider_request_id", "session_id",
        "timeout_seconds", "output_contract",
    }
    if set(request) - expected:
        raise ResearchExecutionError("research execution request fields are invalid")
    required = {
        "schema_ref", "schema_version", "client_id", "cwd", "cwd_boundary", "provider",
        "provider_request_id", "session_id",
    }
    if not required.issubset(request):
        raise ResearchExecutionError("research execution request fields are invalid")
    if request.get("schema_ref") != REQUEST_SCHEMA or request.get("schema_version") != 1:
        raise ResearchExecutionError("research execution request schema is invalid")
    client_id = request.get("client_id")
    if client_id not in policy.clients:
        raise ResearchExecutionError("research execution client is invalid")
    client = policy.clients[str(client_id)]
    platform = _platform_key(platform_name)
    cwd = _resolved_directory(request.get("cwd"), "research execution cwd")
    cwd_boundary = _resolved_directory(request.get("cwd_boundary"), "research execution cwd boundary")
    try:
        cwd.relative_to(cwd_boundary)
    except ValueError as exc:
        raise ResearchExecutionError("research execution cwd escapes its boundary") from exc
    provider = request.get("provider")
    request_id = request.get("provider_request_id")
    session_id = request.get("session_id")
    if not isinstance(provider, str) or not IDENTIFIER.fullmatch(provider):
        raise ResearchExecutionError("research execution provider is invalid")
    if not isinstance(request_id, str) or not SHA256.fullmatch(request_id):
        raise ResearchExecutionError("research execution provider request id is invalid")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise ResearchExecutionError("research execution session id is invalid")
    output_contract = request.get("output_contract", OUTPUT_CONTRACT)
    if output_contract != OUTPUT_CONTRACT:
        raise ResearchExecutionError("research execution output contract is invalid")
    timeout = request.get("timeout_seconds", policy.default_timeout_seconds)
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not 1 <= timeout <= policy.maximum_timeout_seconds
    ):
        raise ResearchExecutionError("research execution timeout is invalid")
    model_ref_value = request.get("model_ref")
    model_ref = None
    if model_ref_value is not None:
        model_ref = _portable_text(model_ref_value, "research model reference", maximum=300)
        if model_ref.startswith("-") or "\n" in model_ref or "\r" in model_ref:
            raise ResearchExecutionError("research model reference is unsafe")
        _reject_sensitive_text(model_ref, "research model reference")
    if client.execution_mode == "operator-mediated-only":
        if "executable_ref" in request and request.get("executable_ref") is not None:
            raise ResearchExecutionError("Gemini does not have an automatic V1 execution adapter")
        return ResearchExecutionPlan(
            str(client_id), client.execution_mode, client.optional, None, cwd, cwd_boundary,
            provider, request_id, session_id, model_ref, (), client.output_format,
            OUTPUT_CONTRACT, timeout, policy.maximum_prompt_bytes, policy.maximum_stdout_bytes,
            policy.maximum_stderr_bytes, policy.environment_allowlist,
            client.allowed_executable_names, policy.blocked_executable_names, platform,
            {},
            "optional-provider-unavailable",
        )
    executable_value = request.get("executable_ref")
    if executable_value is None:
        executable_value = client.default_executable_refs.get(platform)
    if not isinstance(executable_value, str):
        raise ResearchExecutionError("research executable reference is required")
    executable_ref = _validate_executable_ref(
        executable_value, client, policy.blocked_executable_names, platform,
    )
    argv_tail = list(client.base_argv)
    if model_ref is not None:
        argv_tail.extend(model_ref if item == "{model_ref}" else item for item in client.model_argv)
    if any("{prompt}" in item or "{cwd}" in item for item in argv_tail):
        raise ResearchExecutionError("research prompt and cwd must not be command arguments")
    return ResearchExecutionPlan(
        str(client_id), client.execution_mode, client.optional, executable_ref, cwd, cwd_boundary,
        provider, request_id, session_id, model_ref, tuple(argv_tail), client.output_format,
        OUTPUT_CONTRACT, timeout, policy.maximum_prompt_bytes, policy.maximum_stdout_bytes,
        policy.maximum_stderr_bytes, policy.environment_allowlist,
        client.allowed_executable_names, policy.blocked_executable_names, platform,
        {"OPENCODE_CONFIG_CONTENT": OPENCODE_READ_ONLY_CONFIG} if client_id == "opencode" else {},
        "ready",
    )


ExecutableResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class ResearchExecutionProbe:
    client_id: str
    status: str
    available: bool
    executable_ref_sha256: str
    resolved_executable: str | None
    optional: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "status": self.status,
            "available": self.available,
            "executable_ref_sha256": self.executable_ref_sha256,
            "optional": self.optional,
            "physical_paths_included": False,
            "credential_values_included": False,
            "provider_authority_granted": False,
        }


def probe_research_execution(
    plan: ResearchExecutionPlan,
    *,
    executable_resolver: ExecutableResolver = shutil.which,
) -> ResearchExecutionProbe:
    """Perform a read-only availability check for one explicit executable reference."""

    if plan.execution_mode == "operator-mediated-only":
        return ResearchExecutionProbe(
            plan.client_id, "optional-provider-unavailable", False,
            plan.executable_ref_sha256, None, True,
        )
    if plan.executable_ref is None:
        raise ResearchExecutionError("research executable reference is missing")
    reference = plan.executable_ref
    path = Path(reference)
    resolved: str | None
    if path.is_absolute():
        resolved = str(path.resolve(strict=False)) if path.is_file() else None
    else:
        resolved = executable_resolver(reference)
    if resolved is not None:
        resolved_name = _executable_name(resolved)
        if (
            resolved_name not in plan.allowed_executable_names
            or resolved_name in plan.blocked_executable_names
        ):
            raise ResearchExecutionError("resolved research executable is not allowed")
    return ResearchExecutionProbe(
        plan.client_id, "available" if resolved else "unavailable", bool(resolved),
        plan.executable_ref_sha256, resolved, plan.optional,
    )


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stderr_sha256: str | None = None


class ProcessRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin_bytes: bytes,
        timeout_seconds: int,
        cancellation: CancellationSignal | None,
        stdout_limit: int,
        stderr_limit: int,
    ) -> ProcessOutcome: ...


class _BoundedStreamReader:
    def __init__(self, stream: object, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._captured = bytearray()
        self._digest = hashlib.sha256()
        self.truncated = False

    def read(self) -> None:
        while True:
            chunk = self._stream.read(65536)  # type: ignore[attr-defined]
            if not chunk:
                return
            if not isinstance(chunk, bytes):
                chunk = str(chunk).encode("utf-8", errors="replace")
            self._digest.update(chunk)
            remaining = self._limit - len(self._captured)
            if remaining > 0:
                self._captured.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.truncated = True

    @property
    def value(self) -> bytes:
        return bytes(self._captured)

    @property
    def digest(self) -> str:
        return self._digest.hexdigest()


class BoundedSubprocessRunner:
    """Run one argv-only subprocess with bounded, separately drained output."""

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    shell=False,
                    timeout=10,
                )
                return
            except (OSError, subprocess.SubprocessError):
                process.kill()
                return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin_bytes: bytes,
        timeout_seconds: int,
        cancellation: CancellationSignal | None,
        stdout_limit: int,
        stderr_limit: int,
    ) -> ProcessOutcome:
        started = time.monotonic()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(environment), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            creationflags=creationflags, start_new_session=os.name != "nt",
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            self._terminate_tree(process)
            raise ResearchExecutionError("research process streams are unavailable")
        stdout_reader = _BoundedStreamReader(process.stdout, stdout_limit)
        stderr_reader = _BoundedStreamReader(process.stderr, stderr_limit)
        readers = [
            threading.Thread(target=stdout_reader.read, daemon=True),
            threading.Thread(target=stderr_reader.read, daemon=True),
        ]
        for thread in readers:
            thread.start()

        def write_prompt() -> None:
            try:
                process.stdin.write(stdin_bytes)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()

        writer = threading.Thread(target=write_prompt, daemon=True)
        writer.start()
        timed_out = False
        cancelled = False
        deadline = started + timeout_seconds
        while process.poll() is None:
            if cancellation is not None and cancellation.is_set():
                cancelled = True
                self._terminate_tree(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                self._terminate_tree(process)
                break
            time.sleep(0.02)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._terminate_tree(process)
            process.wait(timeout=5)
        for thread in readers:
            thread.join(timeout=5)
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return ProcessOutcome(
            process.returncode, stdout_reader.value, stderr_reader.value, duration_ms,
            timed_out, cancelled, stdout_reader.truncated, stderr_reader.truncated,
            stderr_reader.digest,
        )


@dataclass(frozen=True)
class ResearchExecutionResult:
    status: str
    client_id: str
    provider: str
    provider_request_id: str
    session_id: str
    model_ref: str | None
    response_markdown: str | None
    response_sha256: str | None
    stderr_sha256: str | None
    exit_code: int | None
    duration_ms: int
    stdout_truncated: bool
    stderr_truncated: bool
    executable_ref_sha256: str
    cwd_sha256: str
    output_contract: str = OUTPUT_CONTRACT
    structured_output: Mapping[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        result = {
            "schema_ref": RESULT_SCHEMA,
            "schema_version": 1,
            "status": self.status,
            "client_id": self.client_id,
            "provider": self.provider,
            "provider_request_id": self.provider_request_id,
            "session_id": self.session_id,
            "model_ref": self.model_ref,
            "response_markdown": self.response_markdown,
            "response_sha256": self.response_sha256,
            "stderr_sha256": self.stderr_sha256,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "executable_ref_sha256": self.executable_ref_sha256,
            "cwd_sha256": self.cwd_sha256,
            "output_contract": self.output_contract,
            "provider_authority_granted": False,
            "physical_paths_included": False,
            "credential_values_included": False,
        }
        validate_research_execution_result(result)
        return result


def validate_research_execution_result(result: Mapping[str, object]) -> None:
    expected = {
        "schema_ref", "schema_version", "status", "client_id", "provider",
        "provider_request_id", "session_id", "model_ref", "response_markdown",
        "response_sha256", "stderr_sha256", "exit_code", "duration_ms",
        "stdout_truncated", "stderr_truncated", "executable_ref_sha256", "cwd_sha256",
        "output_contract", "provider_authority_granted", "physical_paths_included",
        "credential_values_included",
    }
    statuses = {
        "completed", "failed", "timeout", "cancelled", "unavailable",
        "optional-provider-unavailable",
    }
    if set(result) != expected:
        raise ResearchExecutionError("research execution result fields are invalid")
    if (
        result.get("schema_ref") != RESULT_SCHEMA
        or result.get("schema_version") != 1
        or result.get("status") not in statuses
        or result.get("client_id") not in _EXPECTED_CLIENTS
        or not isinstance(result.get("provider"), str)
        or not IDENTIFIER.fullmatch(str(result["provider"]))
        or not isinstance(result.get("provider_request_id"), str)
        or not SHA256.fullmatch(str(result["provider_request_id"]))
        or not isinstance(result.get("session_id"), str)
        or not SESSION_ID.fullmatch(str(result["session_id"]))
        or result.get("output_contract") != OUTPUT_CONTRACT
        or result.get("provider_authority_granted") is not False
        or result.get("physical_paths_included") is not False
        or result.get("credential_values_included") is not False
    ):
        raise ResearchExecutionError("research execution result contract is invalid")
    if any(
        not isinstance(result.get(key), str) or not SHA256.fullmatch(str(result[key]))
        for key in ("executable_ref_sha256", "cwd_sha256")
    ):
        raise ResearchExecutionError("research execution result digests are invalid")
    for key in ("response_sha256", "stderr_sha256"):
        value = result.get(key)
        if value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)):
            raise ResearchExecutionError("research execution result digest is invalid")
    if (
        not isinstance(result.get("duration_ms"), int)
        or isinstance(result.get("duration_ms"), bool)
        or int(result["duration_ms"]) < 0
        or not isinstance(result.get("stdout_truncated"), bool)
        or not isinstance(result.get("stderr_truncated"), bool)
        or (result.get("exit_code") is not None and (
            not isinstance(result.get("exit_code"), int)
            or isinstance(result.get("exit_code"), bool)
        ))
    ):
        raise ResearchExecutionError("research execution result values are invalid")
    response = result.get("response_markdown")
    if response is not None:
        if not isinstance(response, str) or not response.strip():
            raise ResearchExecutionError("research execution response is invalid")
        _reject_sensitive_text(response, "research execution response")
    completed = result.get("status") == "completed"
    if completed != bool(response is not None and result.get("response_sha256") and result.get("exit_code") == 0):
        raise ResearchExecutionError("research execution completion result is inconsistent")


def _provider_authorized(plan: ResearchExecutionPlan, authorization: ProviderAuthorization | None) -> None:
    if authorization is None:
        raise ResearchExecutionError("research execution requires provider authorization")
    request = authorization.request
    if (
        request.request_id != plan.provider_request_id
        or request.provider != plan.provider
        or request.session_id != plan.session_id
    ):
        raise ResearchExecutionError("research provider authorization does not match the exact request")
    if request.remote and authorization.approval_verified is not True:
        raise ResearchExecutionError("remote research provider approval is required")


def _parse_json_or_jsonl(value: bytes) -> list[object]:
    try:
        text = value.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ResearchExecutionError("research execution output is not UTF-8") from exc
    if not text:
        raise ResearchExecutionError("research execution output is empty")
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError:
        records: list[object] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ResearchExecutionError("research execution output is not JSON or JSONL") from exc
        if not records:
            raise ResearchExecutionError("research execution output is empty")
        return records


def _text_from_content(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return None


def _extract_assistant_text(records: Sequence[object]) -> str:
    candidates: list[tuple[int, int, str]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        response = record.get("response_markdown")
        if isinstance(response, str) and response.strip():
            candidates.append((100, index, response))
        result = record.get("result")
        if isinstance(result, str) and result.strip():
            candidates.append((90, index, result))
        item = record.get("item")
        if isinstance(item, dict) and item.get("type") in {"agent_message", "assistant_message"}:
            text = _text_from_content(item.get("text")) or _text_from_content(item.get("content"))
            if text:
                candidates.append((80, index, text))
        message = record.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            text = _text_from_content(message.get("content")) or _text_from_content(message.get("text"))
            if text:
                candidates.append((70, index, text))
        if record.get("role") == "assistant" or record.get("type") in {"assistant", "assistant_message"}:
            text = _text_from_content(record.get("content")) or _text_from_content(record.get("text"))
            if text:
                candidates.append((60, index, text))
        part = record.get("part")
        if isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
            text = _text_from_content(part.get("text"))
            if text:
                candidates.append((50, index, text))
    if not candidates:
        raise ResearchExecutionError("research execution output has no assistant text")
    best_priority = max(item[0] for item in candidates)
    return max((item for item in candidates if item[0] == best_priority), key=lambda item: item[1])[2]


def validate_research_agent_output(value: object) -> dict[str, object]:
    """Validate the only CLI payload that may become native completion."""

    if not isinstance(value, Mapping):
        raise ResearchExecutionError("research agent output must be a JSON object")
    payload = dict(value)
    if set(payload) != {"schema_ref", "schema_version", "agent_result", "research_result"}:
        raise ResearchExecutionError("research agent output fields are invalid")
    if payload.get("schema_ref") != AGENT_OUTPUT_SCHEMA or payload.get("schema_version") != 1:
        raise ResearchExecutionError("research agent output schema is invalid")
    agent = payload.get("agent_result")
    required_agent = {"status", "summary", "evidence", "changes", "preserved_areas"}
    optional_agent = {"issues"}
    if (
        not isinstance(agent, Mapping)
        or not required_agent.issubset(agent)
        or set(agent) - required_agent - optional_agent
        or agent.get("status") != "completed"
        or not isinstance(agent.get("summary"), str)
        or not str(agent["summary"]).strip()
    ):
        raise ResearchExecutionError("research agent result is invalid")
    evidence = agent.get("evidence")
    if not isinstance(evidence, list) or any(
        not isinstance(item, Mapping)
        or set(item) - {"kind", "reference", "digest"}
        or not isinstance(item.get("kind"), str)
        or not item.get("kind")
        or not isinstance(item.get("reference"), str)
        or not item.get("reference")
        or (
            item.get("digest") is not None
            and (not isinstance(item.get("digest"), str) or not SHA256.fullmatch(str(item["digest"])))
        )
        for item in evidence
    ):
        raise ResearchExecutionError("research agent evidence is invalid")
    for field in ("changes", "preserved_areas", "issues"):
        items = agent.get(field, [])
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ResearchExecutionError("research agent result list is invalid")
    research = payload.get("research_result")
    if not isinstance(research, Mapping) or set(research) != {"response_markdown", "findings"}:
        raise ResearchExecutionError("structured research result is invalid")
    markdown = research.get("response_markdown")
    findings = research.get("findings")
    if not isinstance(markdown, str) or not markdown.strip() or not isinstance(findings, Mapping):
        raise ResearchExecutionError("structured research content is invalid")
    _portable_text(markdown, "structured research response", maximum=16 * 1024 * 1024)
    _reject_sensitive_text(markdown, "structured research response")
    if set(findings) != {"sources", "claims", "conflicts"} or any(
        not isinstance(findings.get(name), list)
        or any(not isinstance(item, Mapping) for item in findings[name])
        for name in ("sources", "claims", "conflicts")
    ):
        raise ResearchExecutionError("structured research findings are invalid")
    _reject_sensitive_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "structured research agent output",
    )
    return payload


def parse_research_agent_output(text: str) -> dict[str, object]:
    """Reject prose and fenced snippets; only one exact JSON object is accepted."""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResearchExecutionError(
            "research execution output is not structured agent JSON"
        ) from exc
    return validate_research_agent_output(payload)


def _environment(
    allowlist: Sequence[str],
    overrides: Mapping[str, str],
) -> dict[str, str]:
    result = {key: os.environ[key] for key in allowlist if key in os.environ}
    result.update(overrides)
    return result


def _result(
    plan: ResearchExecutionPlan,
    status: str,
    *,
    response: str | None = None,
    stderr_sha256: str | None = None,
    exit_code: int | None = None,
    duration_ms: int = 0,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    structured_output: Mapping[str, object] | None = None,
) -> ResearchExecutionResult:
    value = ResearchExecutionResult(
        status, plan.client_id, plan.provider, plan.provider_request_id, plan.session_id,
        plan.model_ref, response, _digest_text(response) if response is not None else None,
        stderr_sha256, exit_code, duration_ms, stdout_truncated, stderr_truncated,
        plan.executable_ref_sha256, plan.cwd_sha256, OUTPUT_CONTRACT,
        dict(structured_output) if structured_output is not None else None,
    )
    value.as_dict()
    return value


def execute_research_execution(
    plan: ResearchExecutionPlan,
    prompt: str,
    *,
    provider_authorization: ProviderAuthorization | None,
    runner: ProcessRunner | None = None,
    cancellation: CancellationSignal | None = None,
    executable_resolver: ExecutableResolver = shutil.which,
) -> ResearchExecutionResult:
    """Execute one approved client path without granting provider or mutation authority."""

    if plan.execution_mode == "operator-mediated-only":
        return _result(plan, "optional-provider-unavailable")
    prompt = _portable_text(prompt, "research execution prompt", maximum=plan.max_prompt_bytes)
    _reject_sensitive_text(prompt, "research execution prompt")
    _provider_authorized(plan, provider_authorization)
    probe = probe_research_execution(plan, executable_resolver=executable_resolver)
    if not probe.available or probe.resolved_executable is None:
        return _result(plan, "unavailable")
    if cancellation is not None and cancellation.is_set():
        return _result(plan, "cancelled")
    argv = (probe.resolved_executable, *plan.argv_tail)
    process_runner = runner or BoundedSubprocessRunner()
    try:
        outcome = process_runner.run(
            argv, cwd=plan.cwd,
            environment=_environment(plan.environment_allowlist, plan.environment_overrides),
            stdin_bytes=prompt.encode("utf-8"), timeout_seconds=plan.timeout_seconds,
            cancellation=cancellation, stdout_limit=plan.max_stdout_bytes,
            stderr_limit=plan.max_stderr_bytes,
        )
    except OSError:
        return _result(plan, "unavailable")
    stderr_digest = outcome.stderr_sha256 or _digest_bytes(outcome.stderr)
    if outcome.cancelled:
        return _result(
            plan, "cancelled", stderr_sha256=stderr_digest, exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms, stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
        )
    if outcome.timed_out:
        return _result(
            plan, "timeout", stderr_sha256=stderr_digest, exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms, stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
        )
    if outcome.exit_code != 0 or outcome.stdout_truncated:
        return _result(
            plan, "failed", stderr_sha256=stderr_digest, exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms, stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
        )
    try:
        records = _parse_json_or_jsonl(outcome.stdout)
        assistant_text = _extract_assistant_text(records).strip()
        _portable_text(assistant_text, "research execution response", maximum=plan.max_stdout_bytes)
        structured_output = parse_research_agent_output(assistant_text)
        research_result = structured_output["research_result"]
        assert isinstance(research_result, Mapping)
        response = str(research_result["response_markdown"])
    except ResearchExecutionError:
        return _result(
            plan, "failed", stderr_sha256=stderr_digest, exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms, stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
        )
    return _result(
        plan, "completed", response=response, stderr_sha256=stderr_digest,
        exit_code=outcome.exit_code, duration_ms=outcome.duration_ms,
        stdout_truncated=outcome.stdout_truncated, stderr_truncated=outcome.stderr_truncated,
        structured_output=structured_output,
    )

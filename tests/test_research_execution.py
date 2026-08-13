from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.provider_gate import ProviderAuthorization, ProviderRequest  # noqa: E402
from krcn_core.research_execution import (  # noqa: E402
    OUTPUT_CONTRACT,
    ProcessOutcome,
    ResearchExecutionError,
    execute_research_execution,
    load_research_execution_policy,
    probe_research_execution,
    resolve_research_execution,
    validate_research_execution_result,
)


class FakeRunner:
    def __init__(self, outcome: ProcessOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    def run(self, argv, **kwargs):
        self.calls.append({"argv": tuple(argv), **kwargs})
        return self.outcome


class Cancellation:
    def __init__(self, value: bool) -> None:
        self.value = value

    def is_set(self) -> bool:
        return self.value


class ResearchExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.boundary = Path(self.temporary.name).resolve()
        self.cwd = self.boundary / "project"
        self.cwd.mkdir()
        self.policy = load_research_execution_policy(REPO_ROOT)
        self.request_id = "a" * 64
        self.session_id = "research-session-1"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def request(self, client_id: str = "opencode", **changes):
        value = {
            "schema_ref": "schemas/research-execution-request.schema.json",
            "schema_version": 1,
            "client_id": client_id,
            "cwd": str(self.cwd),
            "cwd_boundary": str(self.boundary),
            "provider": "subscription-client",
            "provider_request_id": self.request_id,
            "session_id": self.session_id,
            "model_ref": "provider/model",
            "output_contract": OUTPUT_CONTRACT,
        }
        value.update(changes)
        return value

    @staticmethod
    def agent_output(markdown: str) -> str:
        return json.dumps(
            {
                "schema_ref": "schemas/research-agent-output.schema.json",
                "schema_version": 1,
                "agent_result": {
                    "status": "completed",
                    "summary": "Verified research result",
                    "evidence": [{"kind": "source", "reference": "doc:one"}],
                    "changes": [],
                    "preserved_areas": ["project-source"],
                },
                "research_result": {
                    "response_markdown": markdown,
                    "findings": {"sources": [], "claims": [], "conflicts": []},
                },
            }
        )

    def authorization(self, *, request_id: str | None = None, approved: bool = True):
        request = ProviderRequest(
            request_id or self.request_id,
            "subscription-client",
            "https://provider.invalid/api",
            ("research-prompt",),
            "research-execution",
            "provider terms apply",
            self.session_id,
            True,
        )
        return ProviderAuthorization(request, approved)

    @staticmethod
    def resolver(reference: str) -> str:
        suffix = ".cmd" if reference.endswith(".cmd") else ".exe"
        stem = Path(reference).stem
        return "C:" + f"\\fake\\{stem}{suffix}"

    def test_policy_and_new_schemas_are_valid(self) -> None:
        self.assertEqual(
            {"opencode", "codex-cli", "claude-cli", "gemini"},
            set(self.policy.clients),
        )
        self.assertFalse(self.policy.clients["gemini"].execution_mode == "native-cli")
        for name in (
            "research-execution-policy.schema.json",
            "research-execution-request.schema.json",
            "research-execution-result.schema.json",
        ):
            payload = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(payload)
        request_schema = json.loads(
            (REPO_ROOT / "schemas" / "research-execution-request.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(request_schema).iter_errors(self.request())))

    def test_native_clients_build_fixed_argv_and_keep_prompt_out_of_argv(self) -> None:
        expected = {
            "opencode": (
                "run", "--format", "json", "--pure", "--agent", "krcn-research-read-only",
                "--model", "provider/model",
            ),
            "codex-cli": (
                "exec", "--json", "--ephemeral", "--sandbox", "read-only",
                "--ignore-user-config", "--ignore-rules", "--model", "provider/model",
            ),
            "claude-cli": (
                "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                "--safe-mode", "--permission-mode", "plan", "--tools", "Read,Glob,Grep",
                "--strict-mcp-config", "--mcp-config", "{}", "--disable-slash-commands",
                "--model", "provider/model",
            ),
        }
        for client_id, argv_tail in expected.items():
            with self.subTest(client_id=client_id):
                plan = resolve_research_execution(
                    self.policy, self.request(client_id), platform_name="windows",
                )
                self.assertEqual(argv_tail, plan.argv_tail)
                self.assertNotIn("research prompt", " ".join(plan.argv_tail))
                summary = plan.public_summary()
                self.assertFalse(summary["physical_paths_included"])
                self.assertNotIn(str(self.cwd), str(summary))

    def test_explicit_windows_cmd_and_exe_references_are_supported(self) -> None:
        opencode = resolve_research_execution(
            self.policy,
            self.request("opencode", executable_ref="C:" + "\\Tools\\opencode.cmd"),
            platform_name="windows",
        )
        claude = resolve_research_execution(
            self.policy,
            self.request("claude-cli", executable_ref="C:" + "\\Tools\\claude.exe"),
            platform_name="windows",
        )
        self.assertTrue(opencode.executable_ref.endswith(".cmd"))
        self.assertTrue(claude.executable_ref.endswith(".exe"))

    def test_shells_wrong_client_executables_and_extra_arguments_are_rejected(self) -> None:
        for executable in ("powershell.exe", "cmd.exe", "claude.exe", "opencode.ps1"):
            with self.subTest(executable=executable):
                with self.assertRaises(ResearchExecutionError):
                    resolve_research_execution(
                        self.policy,
                        self.request("opencode", executable_ref=executable),
                        platform_name="windows",
                    )
        with self.assertRaisesRegex(ResearchExecutionError, "fields"):
            resolve_research_execution(
                self.policy,
                self.request("opencode", extra_argv=["--dangerously-bypass-approvals"]),
            )

    def test_cwd_must_exist_and_remain_within_explicit_boundary(self) -> None:
        outside = self.boundary.parent
        with self.assertRaisesRegex(ResearchExecutionError, "escapes"):
            resolve_research_execution(
                self.policy, self.request(cwd=str(outside)), platform_name="windows",
            )
        with self.assertRaisesRegex(ResearchExecutionError, "unavailable"):
            resolve_research_execution(
                self.policy, self.request(cwd=str(self.boundary / "missing")),
            )

    def test_probe_checks_only_the_explicit_reference_and_hides_resolved_path(self) -> None:
        seen = []

        def resolver(reference: str) -> str:
            seen.append(reference)
            return "C:" + "\\private\\opencode.cmd"

        plan = resolve_research_execution(
            self.policy, self.request("opencode"), platform_name="windows",
        )
        probe = probe_research_execution(plan, executable_resolver=resolver)
        self.assertEqual(["opencode.cmd"], seen)
        self.assertTrue(probe.available)
        public = probe.public_summary()
        self.assertNotIn("resolved_executable", public)
        self.assertNotIn("C:" + "\\private", str(public))

    def test_gemini_is_operator_mediated_optional_and_never_runs(self) -> None:
        plan = resolve_research_execution(
            self.policy,
            self.request("gemini", model_ref=None),
            platform_name="windows",
        )
        runner = FakeRunner(ProcessOutcome(0, b"{}", b"", 1))
        result = execute_research_execution(
            plan, "Use the manual research artifact.",
            provider_authorization=None, runner=runner,
        )
        self.assertEqual("optional-provider-unavailable", result.status)
        self.assertEqual([], runner.calls)
        self.assertFalse(result.as_dict()["provider_authority_granted"])

    def test_success_uses_stdin_allowlisted_env_and_validates_jsonl_output(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request("codex-cli"), platform_name="windows",
        )
        structured = json.dumps(self.agent_output("# Final research\n\nVerified relative evidence."))
        output = (
            b'{"type":"thread.started","thread_id":"one"}\n'
            + json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": json.loads(structured)}}
            ).encode("utf-8")
            + b"\n"
        )
        runner = FakeRunner(ProcessOutcome(0, output, b"warning", 42))
        with patch.dict(
            os.environ,
            {"PATH": "safe-path", "OPENAI_API_KEY": "must-not-pass"},
            clear=False,
        ):
            result = execute_research_execution(
                plan, "Run the bounded research role.",
                provider_authorization=self.authorization(), runner=runner,
                executable_resolver=lambda _: "C:" + "\\fake\\codex.cmd",
            )
        self.assertEqual("completed", result.status)
        self.assertEqual("# Final research\n\nVerified relative evidence.", result.response_markdown)
        self.assertEqual(1, len(runner.calls))
        call = runner.calls[0]
        self.assertEqual(b"Run the bounded research role.", call["stdin_bytes"])
        self.assertNotIn("OPENAI_API_KEY", call["environment"])
        self.assertEqual("safe-path", call["environment"]["PATH"])
        self.assertIsInstance(call["argv"], tuple)
        self.assertEqual("C:" + "\\fake\\codex.cmd", call["argv"][0])
        validate_research_execution_result(result.as_dict())
        schema = json.loads(
            (REPO_ROOT / "schemas" / "research-execution-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(result.as_dict())))

    def test_claude_result_and_opencode_assistant_content_are_parsed(self) -> None:
        cases = (
            ("claude-cli", json.dumps({"type": "result", "result": self.agent_output("Claude final")}).encode()),
            (
                "opencode",
                json.dumps({"type": "assistant", "content": [{"type": "text", "text": self.agent_output("OpenCode final")}]}).encode(),
            ),
        )
        for client_id, stdout in cases:
            with self.subTest(client_id=client_id):
                plan = resolve_research_execution(
                    self.policy, self.request(client_id), platform_name="windows",
                )
                runner = FakeRunner(ProcessOutcome(0, stdout, b"", 1))
                result = execute_research_execution(
                    plan, "Prompt packet", provider_authorization=self.authorization(),
                    runner=runner, executable_resolver=self.resolver,
                )
                self.assertEqual("completed", result.status)
                if client_id == "opencode":
                    inline = runner.calls[0]["environment"].get("OPENCODE_CONFIG_CONTENT")
                    self.assertEqual(plan.environment_overrides["OPENCODE_CONFIG_CONTENT"], inline)

    def test_opencode_receives_enforced_nonsecret_read_only_config(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request("opencode"), platform_name="windows",
        )
        override = json.loads(plan.environment_overrides["OPENCODE_CONFIG_CONTENT"])
        permissions = override["agent"]["krcn-research-read-only"]["permission"]
        self.assertEqual("deny", permissions["*"])
        self.assertEqual("allow", permissions["read"])
        for permission in ("edit", "bash", "task", "webfetch", "websearch", "skill", "external_directory"):
            self.assertEqual("deny", permissions[permission])

    def test_exact_provider_authorization_is_required_before_runner(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request(), platform_name="windows",
        )
        runner = FakeRunner(ProcessOutcome(0, b'{"result":"unused"}', b"", 1))
        with self.assertRaisesRegex(ResearchExecutionError, "provider authorization"):
            execute_research_execution(
                plan, "Prompt", provider_authorization=None, runner=runner,
                executable_resolver=self.resolver,
            )
        with self.assertRaisesRegex(ResearchExecutionError, "exact request"):
            execute_research_execution(
                plan, "Prompt",
                provider_authorization=self.authorization(request_id="b" * 64),
                runner=runner, executable_resolver=self.resolver,
            )
        with self.assertRaisesRegex(ResearchExecutionError, "approval"):
            execute_research_execution(
                plan, "Prompt", provider_authorization=self.authorization(approved=False),
                runner=runner, executable_resolver=self.resolver,
            )
        self.assertEqual([], runner.calls)

    def test_timeout_cancellation_limits_and_unavailability_fail_closed(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request(), platform_name="windows",
        )
        cases = (
            (ProcessOutcome(None, b"", b"timeout", 50, timed_out=True), "timeout"),
            (ProcessOutcome(None, b"", b"cancel", 5, cancelled=True), "cancelled"),
            (ProcessOutcome(0, b'{"result":"partial"}', b"", 1, stdout_truncated=True), "failed"),
            (ProcessOutcome(2, b'{"result":"not accepted"}', b"failure", 1), "failed"),
        )
        for outcome, status in cases:
            with self.subTest(status=status, outcome=outcome):
                runner = FakeRunner(outcome)
                result = execute_research_execution(
                    plan, "Prompt", provider_authorization=self.authorization(),
                    runner=runner, executable_resolver=self.resolver,
                )
                self.assertEqual(status, result.status)
                self.assertIsNone(result.response_markdown)
        unavailable = execute_research_execution(
            plan, "Prompt", provider_authorization=self.authorization(),
            runner=FakeRunner(ProcessOutcome(0, b"{}", b"", 1)),
            executable_resolver=lambda _: None,
        )
        self.assertEqual("unavailable", unavailable.status)
        pre_cancelled = FakeRunner(ProcessOutcome(0, b"{}", b"", 1))
        cancelled = execute_research_execution(
            plan, "Prompt", provider_authorization=self.authorization(),
            runner=pre_cancelled, cancellation=Cancellation(True),
            executable_resolver=self.resolver,
        )
        self.assertEqual("cancelled", cancelled.status)
        self.assertEqual([], pre_cancelled.calls)

    def test_invalid_json_secret_and_machine_path_never_escape(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request(), platform_name="windows",
        )
        outputs = (
            b"not json",
            ('{"result":"github_' + 'pat_abcdefghijklmnopqrstuvwxyz1234567890"}').encode(),
            ('{"result":"Read C:' + '\\\\Users\\\\private\\\\secret.txt"}').encode(),
            ('{"result":"Read D:/private/secret.txt"}').encode(),
            b'{"result":"Read /etc/passwd"}',
        )
        for stdout in outputs:
            with self.subTest(stdout=stdout):
                result = execute_research_execution(
                    plan, "Prompt", provider_authorization=self.authorization(),
                    runner=FakeRunner(ProcessOutcome(
                        0, stdout, ("C:" + "\\private\\error").encode(), 1,
                    )),
                    executable_resolver=self.resolver,
                )
                public = result.as_dict()
                self.assertEqual("failed", public["status"])
                self.assertIsNone(public["response_markdown"])
                self.assertNotIn("C:" + "\\private", str(public))
                self.assertNotIn("github_" + "pat", str(public))

    def test_prompt_secret_and_physical_path_are_rejected_before_execution(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request(), platform_name="windows",
        )
        runner = FakeRunner(ProcessOutcome(0, b'{"result":"unused"}', b"", 1))
        for prompt in (
            "Use github_" + "pat_abcdefghijklmnopqrstuvwxyz1234567890",
            "Read C:" + "\\Users\\private\\source.txt",
        ):
            with self.subTest(prompt=prompt):
                with self.assertRaises(ResearchExecutionError):
                    execute_research_execution(
                        plan, prompt, provider_authorization=self.authorization(),
                        runner=runner, executable_resolver=self.resolver,
                    )
        self.assertEqual([], runner.calls)

    def test_structured_output_rejects_general_absolute_locators(self) -> None:
        plan = resolve_research_execution(
            self.policy, self.request("claude-cli"), platform_name="windows",
        )
        for locator in ("D:/private/secret.txt", "/etc/passwd"):
            with self.subTest(locator=locator):
                output = self.agent_output(f"Evidence at {locator}")
                result = execute_research_execution(
                    plan, "Prompt", provider_authorization=self.authorization(),
                    runner=FakeRunner(ProcessOutcome(
                        0, json.dumps({"type": "result", "result": output}).encode(), b"", 1,
                    )),
                    executable_resolver=self.resolver,
                )
                self.assertEqual("failed", result.status)


if __name__ == "__main__":
    unittest.main()

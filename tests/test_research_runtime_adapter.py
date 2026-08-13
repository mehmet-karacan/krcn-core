from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    authorize_provider_request,
    create_provider_request,
    load_provider_gate_policy,
)
from krcn_core.research_execution import (  # noqa: E402
    ProcessOutcome,
    load_research_execution_policy,
    resolve_research_execution,
)
from krcn_core.research_runtime import ResearchRuntimeError, ResearchWorkUnit  # noqa: E402
from krcn_core.research_runtime_adapter import (  # noqa: E402
    bind_research_runtime_adapter,
    create_research_runtime_adapter,
)


class FakeRunner:
    def __init__(self, stdout: bytes) -> None:
        self.stdout = stdout
        self.prompts = []

    def run(self, _argv, **kwargs):
        self.prompts.append(kwargs["stdin_bytes"].decode("utf-8"))
        return ProcessOutcome(0, self.stdout, b"", 5)


class ResearchRuntimeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        provider_request = create_provider_request(
            provider="openai", endpoint="codex-cli-local-session",
            data_categories=("research-prompt",), operation_scope="research-execution",
            retention_assumptions="CLI account policy", session_id="adapter-test", remote=True,
        )
        self.authorization = authorize_provider_request(
            load_provider_gate_policy(REPO_ROOT), provider_request,
            approval=ProviderApproval(provider_request.request_id, "adapter-test", "approved", True),
        )
        request = {
            "schema_ref": "schemas/research-execution-request.schema.json", "schema_version": 1,
            "client_id": "codex-cli", "cwd": str(root), "cwd_boundary": str(root),
            "provider": "openai", "provider_request_id": provider_request.request_id,
            "session_id": "adapter-test", "output_contract": "research-agent-result-v1",
        }
        self.plan = resolve_research_execution(load_research_execution_policy(REPO_ROOT), request)
        self.unit = ResearchWorkUnit("research-one", "researcher", "worker", (), "Research safely.", {})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def client_stdout(content: str) -> bytes:
        return json.dumps({"item": {"type": "agent_message", "text": content}}).encode("utf-8")

    def test_factory_normalizes_only_structured_agent_output(self) -> None:
        payload = {
            "schema_ref": "schemas/research-agent-output.schema.json", "schema_version": 1,
            "agent_result": {
                "status": "completed", "summary": "Done",
                "evidence": [{"kind": "source", "reference": "doc:one"}],
                "changes": [], "preserved_areas": ["project-source"],
            },
            "research_result": {
                "response_markdown": "# Finding\n", "findings": {"sources": [], "claims": [], "conflicts": []},
            },
        }
        runner = FakeRunner(self.client_stdout(json.dumps(payload)))
        adapter = create_research_runtime_adapter(
            self.plan, self.authorization, worker_id="worker-one", runner=runner,
            executable_resolver=lambda _value: "codex.cmd",
        )
        result = adapter(self.unit)
        self.assertEqual("completed", result["agent_result"]["status"])
        self.assertIn("Return exactly one JSON object", runner.prompts[0])

    def test_free_text_is_never_native_completion(self) -> None:
        runner = FakeRunner(self.client_stdout("Looks good to me."))
        adapter = create_research_runtime_adapter(
            self.plan, self.authorization, worker_id="worker-one", runner=runner,
            executable_resolver=lambda _value: "codex.cmd",
        )
        with self.assertRaisesRegex(ResearchRuntimeError, "structured output"):
            adapter(self.unit)

    def test_dependency_chain_is_projected_into_the_structured_prompt(self) -> None:
        def dependency(role: str, marker: str):
            return {
                "agent_result": {
                    "summary": f"summary-{marker}",
                    "evidence": [{"kind": "source", "reference": f"doc:{marker}"}],
                },
                "research_result": {
                    "response_markdown": f"response-{marker}",
                    "findings": {"sources": [], "claims": [{"marker": marker}], "conflicts": []},
                },
                "result_sha256": marker * 64,
            }

        payload = {
            "schema_ref": "schemas/research-agent-output.schema.json", "schema_version": 1,
            "agent_result": {
                "status": "completed", "summary": "Done", "evidence": [],
                "changes": [], "preserved_areas": ["project-source"],
            },
            "research_result": {
                "response_markdown": "# Finding\n", "findings": {"sources": [], "claims": [], "conflicts": []},
            },
        }
        runner = FakeRunner(self.client_stdout(json.dumps(payload)))
        adapter = create_research_runtime_adapter(
            self.plan, self.authorization, worker_id="worker-critic", runner=runner,
            executable_resolver=lambda _value: "codex.cmd",
        )
        critic = ResearchWorkUnit(
            "research-one", "critic", "verifier",
            ("researcher", "architecture-reviewer"), "Critique.",
            {
                "researcher": dependency("researcher", "a"),
                "architecture-reviewer": dependency("architecture-reviewer", "b"),
            },
        )
        adapter(critic)
        critic_prompt = runner.prompts[-1]
        self.assertIn("summary-a", critic_prompt)
        self.assertIn("response-b", critic_prompt)
        synthesizer = ResearchWorkUnit(
            "research-one", "synthesizer", "worker", ("critic",), "Synthesize.",
            {"critic": dependency("critic", "c")},
        )
        adapter(synthesizer)
        self.assertIn("summary-c", runner.prompts[-1])
        self.assertIn("response-c", runner.prompts[-1])

    def test_host_override_execution_scalar_tamper_is_rejected(self) -> None:
        payload = {
            "schema_ref": "schemas/research-agent-output.schema.json", "schema_version": 1,
            "agent_result": {
                "status": "completed", "summary": "Done", "evidence": [],
                "changes": [], "preserved_areas": ["project-source"],
            },
            "research_result": {
                "response_markdown": "# Finding\n", "findings": {"sources": [], "claims": [], "conflicts": []},
            },
        }
        native = create_research_runtime_adapter(
            self.plan, self.authorization, worker_id="worker-one",
            runner=FakeRunner(self.client_stdout(json.dumps(payload))),
            executable_resolver=lambda _value: "codex.cmd",
        )

        def tampered(unit):
            result = dict(native(unit))
            result["execution"] = dict(result["execution"])
            result["execution"]["exit_code"] = True
            result["execution"]["duration_ms"] = -9
            result["execution"]["stdout_truncated"] = "false"
            return result

        bound = bind_research_runtime_adapter(tampered, self.plan, worker_id="worker-one")
        with self.assertRaises(ValueError):
            bound(self.unit)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    ServiceRequest,
    create_application_service,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402


class ResearchApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.service = create_application_service(REPO_ROOT, self.home)
        self.prepare_request = {
            "schema_ref": "schemas/research-run-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "title": "Provider-independent research",
            "question": "Evaluate optional research providers.",
            "context": "OpenCode, Codex CLI, and Claude CLI are the required V1 paths.",
            "acceptance_criteria": [
                "Gemini absence must not block research.",
                "Operator-mediated Markdown import must remain supported.",
            ],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _apply_prepare(self) -> dict[str, object]:
        planned = self.service.execute(
            ServiceRequest("codex", "research.prepare", self.prepare_request)
        )
        plan = planned.data["plan"]
        self.assertEqual("planned", planned.status)
        self.assertFalse(plan["gemini_required"])
        self.assertEqual(
            "optional-provider-unavailable",
            plan["optional_provider_statuses"]["gemini"],
        )
        self.assertEqual(0, plan["provider_calls_planned"])
        self.assertNotIn(str(self.home), json.dumps(planned.as_dict()))
        with self.assertRaisesRegex(ApplicationServiceError, "approval"):
            self.service.execute(
                ServiceRequest(
                    "codex",
                    "research.prepare",
                    self.prepare_request,
                    apply=True,
                    expected_plan_id=str(plan["plan_id"]),
                )
            )
        applied = self.service.execute(
            ServiceRequest(
                "codex",
                "research.prepare",
                self.prepare_request,
                apply=True,
                expected_plan_id=str(plan["plan_id"]),
                approval_id="research-prepare-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        return dict(applied.data)

    def test_prepare_import_and_status_share_exact_plan_boundary(self) -> None:
        self._apply_prepare()
        import_request = {
            "schema_ref": "schemas/research-result-import-request.schema.json",
            "schema_version": 1,
            "research_id": "provider-options",
            "scope": "global",
            "role": "researcher",
            "provider": "gemini-web",
            "model": "declared-unverified",
            "response_markdown": "# Findings\n\nGemini is optional and the other V1 paths remain usable.",
            "findings": {"sources": [], "claims": [], "conflicts": []},
        }
        planned = self.service.execute(
            ServiceRequest("claude", "research.import-response", import_request)
        )
        plan_id = str(planned.data["plan"]["plan_id"])
        self.assertEqual("untrusted", planned.data["plan"]["trust"])
        self.assertNotIn(import_request["response_markdown"], json.dumps(planned.as_dict()))
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            self.service.execute(
                ServiceRequest(
                    "claude",
                    "research.import-response",
                    import_request,
                    apply=True,
                    expected_plan_id="0" * 64,
                    approval_id="research-import-approval",
                )
            )
        applied = self.service.execute(
            ServiceRequest(
                "claude",
                "research.import-response",
                import_request,
                apply=True,
                expected_plan_id=plan_id,
                approval_id="research-import-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertEqual("untrusted", applied.data["result"]["trust"])

        status = self.service.execute(
            ServiceRequest(
                "opencode",
                "research.status",
                {"research_id": "provider-options", "scope": "global"},
            )
        )
        self.assertEqual("ok", status.status)
        self.assertEqual(1, status.data["result"]["response_count"])
        self.assertFalse(status.data["result"]["gemini_required"])
        self.assertEqual(
            "optional-provider-unavailable",
            status.data["result"]["optional_provider_statuses"]["gemini"],
        )
        serialized = json.dumps(status.as_dict(), ensure_ascii=False)
        self.assertNotIn(str(self.home), serialized)
        self.assertNotIn(import_request["response_markdown"], serialized)
        with self.assertRaisesRegex(ApplicationServiceError, "read-only"):
            self.service.execute(
                ServiceRequest(
                    "opencode",
                    "research.status",
                    {"research_id": "provider-options", "scope": "global"},
                    apply=True,
                )
            )

    def test_research_requests_fail_closed_on_unknown_fields_and_secrets(self) -> None:
        unknown = dict(self.prepare_request)
        unknown["provider_api_key"] = "not-a-real-key"
        with self.assertRaisesRegex(ApplicationServiceError, "fields are invalid"):
            self.service.execute(
                ServiceRequest("plugin", "research.prepare", unknown)
            )
        sensitive = dict(self.prepare_request)
        sensitive["context"] = "api_key=abcdefghijklmnop"
        with self.assertRaisesRegex(ApplicationServiceError, "prohibited content"):
            self.service.execute(
                ServiceRequest("plugin", "research.prepare", sensitive)
            )

    def test_cli_research_commands_are_thin_request_file_transports(self) -> None:
        self._apply_prepare()
        prepare_file = self.root / "prepare.json"
        prepare_file.write_text(
            json.dumps(self.prepare_request, ensure_ascii=False),
            encoding="utf-8",
        )
        import_file = self.root / "import.json"
        import_file.write_text(
            json.dumps(
                {
                    "schema_ref": "schemas/research-result-import-request.schema.json",
                    "schema_version": 1,
                    "research_id": "provider-options",
                    "scope": "global",
                    "role": "researcher",
                    "provider": "manual",
                    "model": "declared-unverified",
                    "response_markdown": "# Result\n\nAn operator-mediated result.",
                    "findings": {"sources": [], "claims": [], "conflicts": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        request_file = self.root / "status.json"
        request_file.write_text(
            json.dumps({"research_id": "provider-options", "scope": "global"}),
            encoding="utf-8",
        )
        for command, source, operation in (
            ("prepare", prepare_file, "research.prepare"),
            ("import-response", import_file, "research.import-response"),
            ("status", request_file, "research.status"),
        ):
            with self.subTest(command=command):
                output = io.StringIO()
                error = io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    exit_code = main(
                        [
                            "research",
                            command,
                            "--request-file",
                            str(source),
                            "--repo",
                            str(REPO_ROOT),
                            "--data-root",
                            str(self.home),
                        ]
                    )
                self.assertEqual(0, exit_code, error.getvalue())
                payload = json.loads(output.getvalue())
                self.assertEqual(operation, payload["operation"])
                self.assertNotIn(str(self.home), output.getvalue())
                if command == "status":
                    self.assertTrue(payload["data"]["result"]["found"])


if __name__ == "__main__":
    unittest.main()

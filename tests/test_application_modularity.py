from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import krcn_core.application as application  # noqa: E402
from krcn_core.application_contract import (  # noqa: E402
    APPLICATION_OPERATIONS,
    OPERATIONS,
    ApplicationServiceError,
    ServiceRequest,
    ServiceResponse,
)
from krcn_core.application_registry import (  # noqa: E402
    HANDLER_METHODS,
    bind_application_handlers,
)
from krcn_core.cli.renderers.service_response import (  # noqa: E402
    HUMAN_RENDERER_KEYS,
    render_service_response,
)
from krcn_core.cli.renderers.table import (  # noqa: E402
    display_status,
    display_timestamp,
    shorten,
    text_table,
    work_count_pair,
)
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


class ApplicationModularityTests(unittest.TestCase):
    def test_application_facade_reexports_the_stable_contract(self) -> None:
        self.assertIs(ServiceRequest, application.ServiceRequest)
        self.assertIs(ServiceResponse, application.ServiceResponse)
        self.assertIs(ApplicationServiceError, application.ApplicationServiceError)
        self.assertIs(OPERATIONS, application.OPERATIONS)
        source = (REPO_ROOT / "src" / "krcn_core" / "application.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("class ServiceRequest:", source)
        self.assertNotIn("class ServiceResponse:", source)
        self.assertNotIn("handlers = {", source)

    def test_registry_is_explicit_complete_and_does_not_scan_modules(self) -> None:
        self.assertEqual(set(APPLICATION_OPERATIONS), set(HANDLER_METHODS))
        registry_source = (
            REPO_ROOT / "src" / "krcn_core" / "application_registry.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("pkgutil", registry_source)
        self.assertNotIn("importlib", registry_source)
        self.assertNotIn("glob", registry_source)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".krcn"
            home.mkdir()
            (home / "layout.json").write_bytes(user_home_layout_bytes())
            service = application.KrcnApplicationService(
                REPO_ROOT,
                LocalWorkspaceStore(home, OwnershipResolver.from_repository(REPO_ROOT)),
            )
            handlers = bind_application_handlers(service)
        self.assertEqual(set(APPLICATION_OPERATIONS), set(handlers))
        self.assertTrue(all(callable(handler) for handler in handlers.values()))

    def test_public_schema_operation_enums_match_the_contract(self) -> None:
        for filename in (
            "application-request.schema.json",
            "application-response.schema.json",
        ):
            with self.subTest(filename=filename):
                payload = json.loads(
                    (REPO_ROOT / "schemas" / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    set(OPERATIONS),
                    set(payload["properties"]["operation"]["enum"]),
                )

    def test_cli_renderer_registry_preserves_json_human_and_exit_contracts(self) -> None:
        response = ServiceResponse(
            "a" * 64,
            "project.list",
            "ok",
            {"projects": []},
        )
        human, human_exit = render_service_response(
            response,
            None,
            {"project_menu": lambda data: "Kayıtlı proje bulunamadı."},
        )
        rendered_json, json_exit = render_service_response(response, "json", {})
        self.assertEqual("Kayıtlı proje bulunamadı.", human)
        self.assertEqual(0, human_exit)
        self.assertEqual(response.as_dict(), json.loads(rendered_json))
        self.assertEqual(0, json_exit)
        blocked = ServiceResponse("b" * 64, "model.list", "blocked", {})
        fallback, blocked_exit = render_service_response(blocked, None, {})
        self.assertIn("blocked\tmodel.list", fallback)
        self.assertEqual(3, blocked_exit)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            render_service_response(response, None, {})
        self.assertEqual(
            {
                "project.list",
                "project.resume",
                "work.list",
                "work.documents.migrate-layout",
                "work.documents.process",
                "work.index-readable",
                "research.action",
            },
            set(HUMAN_RENDERER_KEYS),
        )

    def test_table_helpers_are_reusable_and_deterministic(self) -> None:
        first = text_table(["Ad", "Durum"], [["gpu-fusion", "aktif"]])
        second = text_table(["Ad", "Durum"], [["gpu-fusion", "aktif"]])
        self.assertEqual(first, second)
        self.assertIn("gpu-fusion", first)
        self.assertEqual("aktif", display_status("active"))
        self.assertEqual("2026-08-15 12:30", display_timestamp("2026-08-15T12:30:00Z"))
        self.assertLessEqual(len(shorten("x" * 100, 20)), 20)
        self.assertEqual(
            "2/3",
            work_count_pair(
                {"work_counts": {"tasks": {"active": 2, "historical": 3}}},
                "tasks",
            ),
        )


if __name__ == "__main__":
    unittest.main()

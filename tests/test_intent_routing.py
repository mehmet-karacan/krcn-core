from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.intent_routing import (  # noqa: E402
    CLIENTS,
    load_intent_routes,
    project_learning_route,
)
from krcn_core.project_learning_intent import (  # noqa: E402
    parse_project_learning_intent,
)


class IntentRoutingContractTests(unittest.TestCase):
    def test_project_learning_route_is_client_neutral_and_safe(self) -> None:
        route = project_learning_route(REPO_ROOT)
        self.assertEqual("project.learn", route.application_operation)
        self.assertIn(route.application_operation, OPERATIONS)
        self.assertEqual(("local-directory",), route.required_inputs)
        self.assertEqual(
            ("project-name", "project-id", "workspace-id", "binding-id"),
            route.inferred_fields,
        )
        self.assertEqual(CLIENTS, set(route.supported_clients))
        self.assertFalse(route.client_specific)
        self.assertFalse(route.copy_source)
        self.assertTrue(route.exact_plan_required)
        self.assertTrue(route.user_data_approval_required)

    def test_every_configured_term_resolves_through_the_shared_parser(self) -> None:
        route = project_learning_route(REPO_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve()
            for term in route.terms:
                with self.subTest(term=term):
                    intent = parse_project_learning_intent(
                        f"projeyi {term}",
                        source_root=source,
                        intent_terms=route.terms,
                    )
                    self.assertEqual(route.action, intent.action)

    def test_agents_and_generic_clients_reference_the_canonical_route(self) -> None:
        for filename in ("AGENTS.md", "AI-CONTEXT.md"):
            with self.subTest(filename=filename):
                content = (REPO_ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("config/intent-routing.json", content)
                self.assertIn("project.learn", content)
                self.assertIn("Never copy", content)
        self.assertEqual(1, len(load_intent_routes(REPO_ROOT)))


if __name__ == "__main__":
    unittest.main()

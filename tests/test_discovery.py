from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.discovery import (  # noqa: E402
    DiscoveryError,
    LOCAL_DISCOVERY_ADAPTER,
    discover_local_source,
    load_discovery_policy,
)
from krcn_core.source_bindings import parse_source_binding  # noqa: E402
from krcn_core.adapter_gate import (  # noqa: E402
    authorize_adapter_operation,
    prepare_adapter_operation,
)


def tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        stat = path.stat()
        snapshot[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(content).hexdigest(),
        )
    return snapshot


def binding_for(root: Path, *, access: str = "read-only", capabilities=None):
    return parse_source_binding(
        {
            "schema_version": 1,
            "binding_id": "sample-project-local",
            "source_id": "sample-project",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": str(root)},
            "default_access": access,
            "capabilities": capabilities or ["read", "metadata"],
            "policy_refs": [],
            "revision": 1,
        }
    )


def discover(binding, policy):
    request = prepare_adapter_operation(
        LOCAL_DISCOVERY_ADAPTER,
        binding,
        "discover",
        [],
    )
    authorization = authorize_adapter_operation(request)
    return discover_local_source(binding, policy, authorization)


class ReadOnlyDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "src").mkdir()
        (self.root / "pyproject.toml").write_text(
            "[project]\nname = 'sample'\n", encoding="utf-8"
        )
        (self.root / "package.json").write_text(
            '{"name":"sample"}\n', encoding="utf-8"
        )
        (self.root / "docs" / "guide.md").write_text(
            "Secret-like sample is not returned as content.\n", encoding="utf-8"
        )
        (self.root / "src" / "main.py").write_text("print('sample')\n", encoding="utf-8")
        (self.root / ".env").write_text("SAMPLE_SECRET=value\n", encoding="utf-8")
        (self.root / "cache.db").write_bytes(b"synthetic database")
        self.policy = load_discovery_policy(REPO_ROOT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_discovery_is_deterministic_read_only_and_redacted(self) -> None:
        before = tree_snapshot(self.root)
        first = discover(binding_for(self.root), self.policy)
        second = discover(binding_for(self.root), self.policy)
        self.assertEqual(before, tree_snapshot(self.root))
        self.assertEqual(first.root_digest, second.root_digest)
        payload = first.as_dict()
        self.assertNotIn(str(self.root), json.dumps(payload))
        self.assertEqual({"Node.js", "Python"}, set(first.technologies))
        paths = {item.relative_path for item in first.files}
        self.assertIn("docs/guide.md", paths)
        self.assertIn("src/main.py", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("cache.db", paths)
        self.assertGreaterEqual(first.skipped["blocked"], 2)

    def test_discovery_returns_hashes_not_file_content(self) -> None:
        result = discover(binding_for(self.root), self.policy)
        serialized = json.dumps(result.as_dict())
        self.assertNotIn("Secret-like sample", serialized)
        for item in result.files:
            self.assertRegex(item.sha256, r"^[a-f0-9]{64}$")

    def test_large_files_are_skipped(self) -> None:
        policy = dict(self.policy)
        policy["maximum_text_file_bytes"] = 4
        result = discover(binding_for(self.root), policy)
        self.assertGreater(result.skipped["too_large"], 0)

    def test_generated_dependency_trees_are_pruned_before_file_limit(self) -> None:
        for directory_name in ("node_modules", ".next", "target", "dist", "build"):
            generated = self.root / directory_name
            generated.mkdir()
            for index in range(20):
                (generated / f"generated-{index}.txt").write_text(
                    "generated dependency output\n",
                    encoding="utf-8",
                )
        result = discover_local_source(
            binding_for(self.root),
            self.policy,
            authorize_adapter_operation(
                prepare_adapter_operation(
                    LOCAL_DISCOVERY_ADAPTER,
                    binding_for(self.root),
                    "discover",
                    [],
                )
            ),
            maximum_files=4,
        )
        paths = {item.relative_path for item in result.files}
        self.assertFalse(
            any(
                path.split("/", 1)[0]
                in {"node_modules", ".next", "target", "dist", "build"}
                for path in paths
            )
        )
        self.assertGreaterEqual(result.skipped["blocked"], 5)

    def test_read_write_binding_is_rejected(self) -> None:
        binding = binding_for(
            self.root,
            access="read-write",
            capabilities=["read", "write", "metadata"],
        )
        with self.assertRaisesRegex(DiscoveryError, "read-only"):
            request = prepare_adapter_operation(
                LOCAL_DISCOVERY_ADAPTER, binding, "discover", []
            )
            discover_local_source(
                binding,
                self.policy,
                authorize_adapter_operation(request),
            )

    def test_missing_metadata_capability_is_rejected(self) -> None:
        binding = binding_for(self.root, capabilities=["read"])
        with self.assertRaisesRegex(ValueError, "metadata"):
            discover(binding, self.policy)

    def test_symlink_is_not_followed_when_supported(self) -> None:
        target = self.root / "src" / "main.py"
        link = self.root / "linked.py"
        try:
            os.symlink(target, link)
        except OSError:
            self.skipTest("symbolic links are unavailable in this environment")
        result = discover(binding_for(self.root), self.policy)
        self.assertNotIn("linked.py", {item.relative_path for item in result.files})
        self.assertEqual(1, result.skipped["symlink"])


if __name__ == "__main__":
    unittest.main()

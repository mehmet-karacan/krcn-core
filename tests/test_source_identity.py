from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.discovery import DiscoveryResult, FileEvidence  # noqa: E402
from krcn_core.source_identity import (  # noqa: E402
    SourceIdentityError,
    assert_external_source,
    identities_match,
    parse_source_identity,
    source_identity_from_discovery,
)


def discovery() -> DiscoveryResult:
    files = (FileEvidence("src/main.py", "source", 12, "a" * 64),)
    digest = hashlib.sha256(
        json.dumps(
            [item.as_dict() for item in files],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return DiscoveryResult(
        binding_id="sample-project-local",
        source_id="sample-project",
        binding_revision=1,
        root_digest=digest,
        files=files,
        technologies=("Python",),
        skipped={"blocked": 0, "symlink": 0, "too_large": 0, "unstable": 0, "unreadable": 0},
    )


class SourceIdentityTests(unittest.TestCase):
    def test_identity_is_path_independent_and_schema_valid(self) -> None:
        identity = source_identity_from_discovery(discovery())
        parsed = parse_source_identity(identity.as_dict())
        self.assertTrue(identities_match(identity, parsed))
        self.assertNotIn("path", json.dumps(identity.as_dict()))
        self.assertEqual(1, identity.file_count)

    def test_changed_digest_does_not_match(self) -> None:
        expected = source_identity_from_discovery(discovery())
        changed = parse_source_identity({**expected.as_dict(), "digest": "b" * 64})
        self.assertFalse(identities_match(expected, changed))

    def test_source_and_user_home_must_be_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "projects" / "sample"
            user_home = root / "krcn-home"
            source.mkdir(parents=True)
            user_home.mkdir()
            self.assertEqual(
                (source.resolve(), user_home.resolve()),
                assert_external_source(source, user_home),
            )
            with self.assertRaisesRegex(SourceIdentityError, "inside KRCN"):
                assert_external_source(user_home / "copied-project", user_home)

    def test_schema_is_versioned(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "source-identity.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:source-identity:1", schema["$id"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.json_documents import (  # noqa: E402
    JsonDocumentError,
    canonical_json_bytes,
    format_json_file,
    parse_json_bytes,
    pretty_json_bytes,
)


class JsonDocumentTests(unittest.TestCase):
    def test_canonical_identity_is_compact_and_key_order_independent(self) -> None:
        first = canonical_json_bytes({"z": 1, "a": "Türkçe"})
        second = canonical_json_bytes({"a": "Türkçe", "z": 1})
        self.assertEqual(first, second)
        self.assertEqual(b'{"a":"T\xc3\xbcrk\xc3\xa7e","z":1}', first)

    def test_pretty_document_is_sorted_readable_and_terminated(self) -> None:
        document = pretty_json_bytes({"z": 1, "a": {"value": True}})
        self.assertTrue(document.endswith(b"\n"))
        self.assertIn(b'\n  "a": {\n', document)
        self.assertLess(document.index(b'"a"'), document.index(b'"z"'))
        self.assertEqual(
            {"a": {"value": True}, "z": 1},
            parse_json_bytes(document),
        )

    def test_invalid_document_is_rejected(self) -> None:
        with self.assertRaisesRegex(JsonDocumentError, "invalid"):
            parse_json_bytes(b"{", label="fixture")

    def test_non_finite_number_is_rejected(self) -> None:
        with self.assertRaisesRegex(JsonDocumentError, "invalid"):
            parse_json_bytes(b'{"value":NaN}', label="fixture")

    def test_source_formatter_preserves_declared_key_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text('{"z":1,"a":2}', encoding="utf-8")
            self.assertTrue(format_json_file(path, check=True))
            self.assertTrue(format_json_file(path, check=False))
            self.assertFalse(format_json_file(path, check=True))
            self.assertEqual(
                ["z", "a"],
                list(json.loads(path.read_text(encoding="utf-8"))),
            )


if __name__ == "__main__":
    unittest.main()

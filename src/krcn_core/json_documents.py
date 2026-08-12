"""Shared JSON encoding rules for identities and human-readable documents."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path


class JsonDocumentError(ValueError):
    """Raised when a JSON document cannot be decoded or encoded safely."""


def canonical_json_bytes(
    payload: object,
    *,
    trailing_newline: bool = False,
) -> bytes:
    """Encode stable compact bytes for hashing and identity calculations."""

    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise JsonDocumentError("value is not JSON-compatible") from exc
    if trailing_newline:
        text += "\n"
    return text.encode("utf-8")


def pretty_json_bytes(
    payload: object,
    *,
    sort_keys: bool = True,
) -> bytes:
    """Encode one deterministic, readable UTF-8 JSON document."""

    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=sort_keys,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise JsonDocumentError("value is not JSON-compatible") from exc
    return (text + "\n").encode("utf-8")


def parse_json_bytes(document: bytes, *, label: str = "JSON document") -> object:
    """Decode strict UTF-8 JSON bytes with one stable public error."""

    def reject_non_finite(value: str) -> object:
        raise ValueError(f"non-finite number is not valid JSON: {value}")

    try:
        return json.loads(
            document.decode("utf-8"),
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise JsonDocumentError(f"{label} is invalid") from exc


def format_json_file(path: Path, *, check: bool) -> bool:
    """Check or normalize one JSON source file while preserving key order."""

    current = path.read_bytes()
    payload = parse_json_bytes(current, label=str(path))
    expected = pretty_json_bytes(payload, sort_keys=False)
    if current == expected:
        return False
    if not check:
        if path.is_symlink() or not path.is_file():
            raise JsonDocumentError(f"{path} must be a regular file")
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(expected)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.chmod(temporary_name, stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary_name, path)
            temporary_name = None
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
    return True

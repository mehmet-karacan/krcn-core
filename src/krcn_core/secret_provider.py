"""Explicit local secret providers that never expose values in summaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .integrations import validate_secret_reference


MAX_SECRET_BYTES = 65_536


class SecretProviderError(ValueError):
    """Raised when an exact secret reference cannot be resolved safely."""


@dataclass(frozen=True)
class SecretLease:
    reference_scheme: str
    value: bytes
    value_digest: str

    def reveal(self) -> bytes:
        return self.value

    def public_summary(self) -> dict[str, object]:
        return {
            "reference_scheme": self.reference_scheme,
            "value_digest": self.value_digest,
            "value_disclosed": False,
        }


class LocalFileSecretProvider:
    """Resolve explicit `secret://` references under one protected local root."""

    def __init__(self, secret_root: Path) -> None:
        if not secret_root.is_absolute():
            raise SecretProviderError("secret root must be absolute")
        self._root = secret_root.resolve(strict=False)

    def resolve(self, reference: str) -> SecretLease:
        try:
            validated = validate_secret_reference(reference)
        except ValueError as exc:
            raise SecretProviderError(str(exc)) from exc
        scheme, value = validated.split("://", 1)
        if scheme != "secret":
            raise SecretProviderError("local file provider requires secret scheme")
        parts = PurePosixPath(value).parts
        target = self._root.joinpath(*parts[:-1], f"{parts[-1]}.secret")
        try:
            target.resolve(strict=False).relative_to(self._root)
        except ValueError as exc:
            raise SecretProviderError("secret reference escapes provider root") from exc
        current = self._root
        for part in (*parts[:-1], f"{parts[-1]}.secret"):
            current = current / part
            if current.is_symlink():
                raise SecretProviderError("secret path may not use symbolic links")
        if not target.is_file():
            raise SecretProviderError("referenced secret is unavailable")
        if target.stat().st_size > MAX_SECRET_BYTES:
            raise SecretProviderError("referenced secret exceeds size limit")
        value_bytes = target.read_bytes()
        if not value_bytes:
            raise SecretProviderError("referenced secret is empty")
        return SecretLease(
            "secret",
            value_bytes,
            hashlib.sha256(value_bytes).hexdigest(),
        )


class OpenCodeSecretProvider:
    """Resolve one explicit OpenCode provider credential without copying it."""

    def __init__(self, config_path: Path) -> None:
        if not config_path.is_absolute():
            raise SecretProviderError("OpenCode config path must be absolute")
        if config_path.is_symlink() or not config_path.is_file():
            raise SecretProviderError("OpenCode config must be a regular file")
        if config_path.stat().st_size > MAX_SECRET_BYTES:
            raise SecretProviderError("OpenCode config exceeds size limit")
        self._config_path = config_path.resolve()

    def resolve(self, reference: str) -> SecretLease:
        try:
            validated = validate_secret_reference(reference)
        except ValueError as exc:
            raise SecretProviderError(str(exc)) from exc
        scheme, value = validated.split("://", 1)
        if scheme != "opencode":
            raise SecretProviderError("OpenCode provider requires opencode scheme")
        parts = PurePosixPath(value).parts
        if len(parts) != 2 or parts[1] != "api-key":
            raise SecretProviderError("OpenCode secret reference is invalid")
        provider_id = parts[0]
        try:
            payload = json.loads(
                self._config_path.read_text(encoding="utf-8-sig")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretProviderError("OpenCode config is invalid") from exc
        try:
            api_key = payload["provider"][provider_id]["options"]["apiKey"]
        except (KeyError, TypeError) as exc:
            raise SecretProviderError("OpenCode provider credential is unavailable") from exc
        if not isinstance(api_key, str) or not api_key:
            raise SecretProviderError("OpenCode provider credential is unavailable")
        value_bytes = api_key.encode("utf-8")
        if len(value_bytes) > MAX_SECRET_BYTES:
            raise SecretProviderError("OpenCode provider credential exceeds size limit")
        return SecretLease(
            "opencode",
            value_bytes,
            hashlib.sha256(value_bytes).hexdigest(),
        )

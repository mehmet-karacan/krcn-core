"""Explicit local secret providers that never expose values in summaries."""

from __future__ import annotations

import hashlib
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

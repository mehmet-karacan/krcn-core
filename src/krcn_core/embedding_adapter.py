"""Provider-gated OpenAI-compatible embedding adapter with explicit fallback."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .embedding_models import (
    EmbeddingIntegrationProfile,
    EmbeddingModelCatalog,
    EmbeddingModelError,
    EmbeddingModelProfile,
)
from .provider_gate import (
    ProviderApproval,
    ProviderAuthorization,
    ProviderGateError,
    ProviderRequest,
    authorize_provider_request,
    create_provider_request,
)
from .secret_provider import OpenCodeSecretProvider, SecretProviderError


MAX_BATCH_SIZE = 128
MAX_TEXT_CHARACTERS = 1_000_000
EMBEDDING_OPERATION_SCOPE = "embedding-generate"
ALLOWED_DATA_CATEGORIES = {"knowledge-content", "query-text", "synthetic-test"}


class EmbeddingProviderError(ValueError):
    """Raised when an approved embedding provider response is unsafe or invalid."""


EmbeddingTransport = Callable[
    [str, bytes, str, tuple[str, ...], int],
    object,
]


@dataclass(frozen=True)
class EmbeddingBatch:
    profile_id: str
    provider_id: str
    model_id: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]
    attempted_profile_ids: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "dimensions": self.dimensions,
            "vector_count": len(self.vectors),
            "attempted_profile_ids": list(self.attempted_profile_ids),
            "remote": True,
            "input_disclosed": False,
            "credential_disclosed": False,
        }


def create_embedding_provider_request(
    profile: EmbeddingModelProfile,
    integration: EmbeddingIntegrationProfile,
    *,
    data_category: str,
    session_id: str,
) -> ProviderRequest:
    if data_category not in ALLOWED_DATA_CATEGORIES:
        raise EmbeddingProviderError("embedding data category is invalid")
    try:
        return create_provider_request(
            provider=profile.provider_id,
            endpoint=integration.endpoint,
            data_categories=(data_category,),
            operation_scope=EMBEDDING_OPERATION_SCOPE,
            retention_assumptions=integration.retention_assumptions,
            session_id=session_id,
            remote=True,
        )
    except ProviderGateError as exc:
        raise EmbeddingProviderError(str(exc)) from exc


def _http_transport(
    endpoint: str,
    api_key: bytes,
    model_id: str,
    texts: tuple[str, ...],
    timeout_seconds: int,
) -> object:
    try:
        credential = api_key.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EmbeddingProviderError("embedding credential encoding is invalid") from exc
    document = json.dumps(
        {
            "model": model_id,
            "input": list(texts),
            "encoding_format": "float",
        },
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/embeddings",
        data=document,
        headers={
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "krcn-core-embedding-adapter",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise EmbeddingProviderError("embedding provider returned a non-success status")
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise EmbeddingProviderError(
            f"embedding provider request failed with HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmbeddingProviderError("embedding provider is unavailable") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbeddingProviderError("embedding provider response is invalid") from exc


def _normalize_vector(value: object, dimensions: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != dimensions:
        raise EmbeddingProviderError("embedding vector dimensions are invalid")
    numbers: list[float] = []
    for item in value:
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
        ):
            raise EmbeddingProviderError("embedding vector values are invalid")
        numbers.append(float(item))
    norm = math.sqrt(sum(item * item for item in numbers))
    if not norm:
        raise EmbeddingProviderError("embedding vector norm is invalid")
    return tuple(float(f"{item / norm:.12f}") for item in numbers)


def _parse_response(
    payload: object,
    *,
    expected_count: int,
    dimensions: int,
) -> tuple[tuple[float, ...], ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise EmbeddingProviderError("embedding provider response fields are invalid")
    data = payload["data"]
    if len(data) != expected_count:
        raise EmbeddingProviderError("embedding provider response count is invalid")
    indexed: dict[int, tuple[float, ...]] = {}
    for position, item in enumerate(data):
        if not isinstance(item, dict):
            raise EmbeddingProviderError("embedding provider response item is invalid")
        index = item.get("index", position)
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= expected_count
            or index in indexed
        ):
            raise EmbeddingProviderError("embedding provider response index is invalid")
        indexed[index] = _normalize_vector(item.get("embedding"), dimensions)
    if set(indexed) != set(range(expected_count)):
        raise EmbeddingProviderError("embedding provider response order is incomplete")
    return tuple(indexed[index] for index in range(expected_count))


class OpenAICompatibleEmbeddingAdapter:
    """Call only an explicitly configured and authorized embedding integration."""

    def __init__(
        self,
        catalog: EmbeddingModelCatalog,
        integration: EmbeddingIntegrationProfile,
        secret_provider: OpenCodeSecretProvider,
        policy: Mapping[str, object],
        *,
        timeout_seconds: int = 90,
        transport: EmbeddingTransport | None = None,
    ) -> None:
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
            raise EmbeddingProviderError("embedding timeout is invalid")
        self._catalog = catalog
        self._integration = integration
        self._secret_provider = secret_provider
        self._policy = dict(policy)
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _http_transport

    def _authorized_request(
        self,
        profile: EmbeddingModelProfile,
        request: ProviderRequest,
        approval: ProviderApproval | None,
    ) -> ProviderAuthorization:
        if profile.profile_id not in self._integration.model_profile_ids:
            raise EmbeddingProviderError("embedding profile is not enabled by integration")
        expected = create_embedding_provider_request(
            profile,
            self._integration,
            data_category=request.data_categories[0]
            if len(request.data_categories) == 1
            else "",
            session_id=request.session_id,
        )
        if request != expected:
            raise EmbeddingProviderError("embedding provider request is not exact")
        try:
            return authorize_provider_request(
                self._policy,
                request,
                approval=approval,
            )
        except ProviderGateError as exc:
            raise EmbeddingProviderError(str(exc)) from exc

    def embed(
        self,
        profile_id: str,
        texts: Sequence[str],
        request: ProviderRequest,
        *,
        approval: ProviderApproval | None,
        attempted_profile_ids: tuple[str, ...] = (),
    ) -> EmbeddingBatch:
        try:
            profile = self._catalog.profile(profile_id)
        except EmbeddingModelError as exc:
            raise EmbeddingProviderError(str(exc)) from exc
        text_tuple = tuple(texts)
        if (
            not text_tuple
            or len(text_tuple) > MAX_BATCH_SIZE
            or any(not isinstance(item, str) or not item for item in text_tuple)
            or sum(len(item) for item in text_tuple) > MAX_TEXT_CHARACTERS
        ):
            raise EmbeddingProviderError("embedding input batch is invalid")
        self._authorized_request(profile, request, approval)
        try:
            lease = self._secret_provider.resolve(
                self._integration.credential_reference
            )
        except SecretProviderError as exc:
            raise EmbeddingProviderError(str(exc)) from exc
        payload = self._transport(
            self._integration.endpoint,
            lease.reveal(),
            profile.model_id,
            text_tuple,
            self._timeout_seconds,
        )
        vectors = _parse_response(
            payload,
            expected_count=len(text_tuple),
            dimensions=profile.vector_dimensions,
        )
        attempts = (*attempted_profile_ids, profile.profile_id)
        return EmbeddingBatch(
            profile.profile_id,
            profile.provider_id,
            profile.model_id,
            profile.vector_dimensions,
            vectors,
            attempts,
        )

    def embed_with_fallback(
        self,
        texts: Sequence[str],
        *,
        requests: Mapping[str, ProviderRequest],
        approvals: Mapping[str, ProviderApproval],
    ) -> EmbeddingBatch:
        attempted: list[str] = []
        for profile_id in self._integration.model_profile_ids:
            profile = self._catalog.profile(profile_id)
            request = requests.get(profile.profile_id)
            approval = approvals.get(profile.profile_id)
            if request is None or approval is None:
                raise EmbeddingProviderError(
                    "embedding fallback requires exact request and approval per profile"
                )
            try:
                return self.embed(
                    profile.profile_id,
                    texts,
                    request,
                    approval=approval,
                    attempted_profile_ids=tuple(attempted),
                )
            except EmbeddingProviderError:
                attempted.append(profile.profile_id)
        raise EmbeddingProviderError(
            "all approved remote embedding profiles are unavailable; use deterministic-hashing"
        )

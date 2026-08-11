"""Deterministic natural-language intent and local directory resolution."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAX_REQUEST_TEXT = 4096
SENSITIVE_TEXT = re.compile(
    r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*[:=]|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+|"
    r"://[^/\s:@]+:[^/@\s]+@"
)
WINDOWS_PATH_START = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/]")
POSIX_PATH_START = re.compile(r"(?<![A-Za-z0-9_:/])/(?!/)")
INTENT_TERMS = {
    "ogren",
    "tani",
    "tanit",
    "entegre",
    "kaydet",
    "learn",
    "recognize",
    "register",
    "onboard",
    "integrate",
}


class ProjectLearningIntentError(ValueError):
    """Raised when a project-learning request is ambiguous or unsafe."""


@dataclass(frozen=True)
class ProjectLearningIntent:
    request_digest: str
    source_root: Path
    action: str
    intent_origin: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-learning-intent.schema.json",
            "schema_version": 1,
            "request_digest": self.request_digest,
            "action": self.action,
            "intent_origin": self.intent_origin,
            "source_kind": "project",
            "locator_kind": "local-path",
            "directory_provided": True,
            "path_disclosed": False,
        }


def _normalized_words(value: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(
        character
        for character in folded
        if not unicodedata.combining(character)
    )
    ascii_like = ascii_like.translate(str.maketrans({"ı": "i", "ş": "s"}))
    return set(re.findall(r"[a-z]+", ascii_like))


def _normalized_terms(values: Iterable[str]) -> set[str]:
    return {
        word
        for value in values
        for word in _normalized_words(value)
    }


def _validated_directory(candidate: Path) -> Path | None:
    if not candidate.is_absolute() or candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if resolved == Path(resolved.anchor):
        return None
    return resolved if resolved.is_dir() else None


def _direct_directory(value: str) -> Path | None:
    stripped = value.strip().strip("\"'")
    return _validated_directory(Path(stripped)) if stripped else None


def _longest_directory_prefix(text: str, start: int) -> Path | None:
    tail = text[start:]
    for end in range(len(tail), 1, -1):
        candidate = tail[:end].strip().strip("\"'.,;:()[]{}")
        if not candidate:
            continue
        resolved = _validated_directory(Path(candidate))
        if resolved is not None:
            return resolved
    return None


def _directories_from_text(text: str) -> set[Path]:
    directories: set[Path] = set()
    direct = _direct_directory(text)
    if direct is not None:
        directories.add(direct)
    for quoted in re.findall(r"[\"']([^\"']+)[\"']", text):
        resolved = _direct_directory(quoted)
        if resolved is not None:
            directories.add(resolved)
    starts = {match.start() for match in WINDOWS_PATH_START.finditer(text)}
    starts.update(match.start() for match in POSIX_PATH_START.finditer(text))
    for start in sorted(starts):
        resolved = _longest_directory_prefix(text, start)
        if resolved is not None:
            directories.add(resolved)
    return directories


def parse_project_learning_intent(
    request_text: str,
    *,
    source_root: Path | None = None,
    intent_terms: Iterable[str] | None = None,
) -> ProjectLearningIntent:
    """Resolve one existing directory and a supported project-learning intent."""

    if not isinstance(request_text, str):
        raise ProjectLearningIntentError("project-learning request must be text")
    normalized = unicodedata.normalize("NFC", request_text).strip()
    if (
        not normalized
        or len(normalized) > MAX_REQUEST_TEXT
        or SENSITIVE_TEXT.search(normalized)
    ):
        raise ProjectLearningIntentError("project-learning request is invalid or sensitive")

    explicit = None
    if source_root is not None:
        explicit = _validated_directory(source_root)
        if explicit is None:
            raise ProjectLearningIntentError(
                "explicit project directory must be an existing absolute regular directory"
            )
    directories = {explicit} if explicit is not None else _directories_from_text(normalized)
    directories.discard(None)
    if not directories:
        raise ProjectLearningIntentError(
            "project-learning request must contain one existing absolute directory"
        )
    if len(directories) != 1:
        raise ProjectLearningIntentError(
            "project-learning request must resolve exactly one directory"
        )
    resolved = next(iter(directories))
    direct_only = _direct_directory(normalized) == resolved
    supported_terms = (
        INTENT_TERMS
        if intent_terms is None
        else _normalized_terms(intent_terms)
    )
    has_intent = bool(_normalized_words(normalized) & supported_terms)
    if not direct_only and not has_intent:
        raise ProjectLearningIntentError(
            "project-learning action was not recognized"
        )
    return ProjectLearningIntent(
        request_digest=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        source_root=resolved,
        action="learn-project",
        intent_origin="safe-assumption" if direct_only else "explicit-user",
    )

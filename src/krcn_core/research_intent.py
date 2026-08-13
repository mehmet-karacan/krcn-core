"""Deterministic natural-language routing for explicit research requests."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .foundation import load_json
from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SECRET = re.compile(
    r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*\S+|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{12,}|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"
)
WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s'\"`(])(?:[a-z]:[\\/]|\\\\)[^\s'\"`)]*")
POSIX_PATH = re.compile(r"(?:^|[\s'\"`(])/(?!/)(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MODES = ("quick", "standard", "deep", "comparison", "root-cause")
OUTCOMES = ("research-only", "research-and-plan", "research-and-implement")
DEICTIC_WORDS = {
    "bunu", "sunu", "onu", "bu", "su", "konu", "konuyu", "this", "that",
    "it", "topic", "the", "please", "lutfen", "hakkinda", "icin", "about",
    "detayli", "derinlemesine", "kapsamli", "hizli", "hizlica", "kisa", "bir",
    "sekilde", "olarak", "briefly", "thoroughly", "quick", "deep", "comprehensive",
}
GENERIC_REFERENTS = {
    "hata", "hatayi", "hatanin", "sorun", "sorunu", "problem", "error",
    "issue", "yaklasim", "yaklasimi", "approach", "sey", "konu", "topic",
}
COMPARISON_CONNECTORS = {"ile", "ve", "vs", "versus", "with", "and", "or"}
PROJECT_WORDS = {
    "proje", "projeyi", "projede", "projedeki", "projesi", "projesini",
    "projesinde", "projeyle", "project", "projects",
}
RESERVED_LIFECYCLE = re.compile(
    r"^(?:"
    r"(?:show|get|list) research (?:status|history|results?)|"
    r"research (?:status|history|results?|cancel|resume)|"
    r"(?:cancel|resume|stop) (?:the )?research"
    r")$"
)


class ResearchIntentError(ValueError):
    """Raised when an explicit research request is unsafe or malformed."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _normalized(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(character for character in folded if not unicodedata.combining(character))
    ascii_like = ascii_like.translate(str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ç": "c", "ö": "o", "ü": "u"}))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_like))


def _phrases(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ResearchIntentError(f"{label} must be a non-empty phrase list")
    normalized = tuple(_normalized(item) for item in value)
    if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        raise ResearchIntentError(f"{label} contains an invalid or duplicate phrase")
    return normalized


def _load_policy(repo_root: Path) -> dict[str, object]:
    payload = load_json(repo_root / "config" / "research-intent.json")
    expected = {
        "schema_ref", "schema_version", "max_request_bytes",
        "explicit_research_phrases", "mode_markers", "outcome_markers",
        "project_references", "context_references", "generic_nonresearch_phrases",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ResearchIntentError("research intent policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/research-intent-policy.schema.json"
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("max_request_bytes"), int)
        or isinstance(payload.get("max_request_bytes"), bool)
        or not 256 <= int(payload["max_request_bytes"]) <= 65536
        or payload.get("invariants") != {
            "generic_action_is_research": False,
            "intent_grants_authority": False,
            "raw_request_in_public_summary": False,
            "physical_paths_in_public_summary": False,
            "credential_values_in_public_summary": False,
        }
    ):
        raise ResearchIntentError("research intent policy invariants are invalid")
    mode_markers = payload.get("mode_markers")
    outcome_markers = payload.get("outcome_markers")
    if not isinstance(mode_markers, dict) or set(mode_markers) != set(MODES) - {"standard"}:
        raise ResearchIntentError("research intent mode markers are invalid")
    if not isinstance(outcome_markers, dict) or set(outcome_markers) != set(OUTCOMES) - {"research-only"}:
        raise ResearchIntentError("research intent outcome markers are invalid")
    result = dict(payload)
    for name in (
        "explicit_research_phrases", "project_references", "context_references",
        "generic_nonresearch_phrases",
    ):
        result[name] = _phrases(payload[name], name)
    result["mode_markers"] = {
        name: _phrases(mode_markers[name], f"mode {name}") for name in mode_markers
    }
    result["outcome_markers"] = {
        name: _phrases(outcome_markers[name], f"outcome {name}") for name in outcome_markers
    }
    return result


def _contains(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_contains(text, phrase) for phrase in phrases)


def _has_stem(words: set[str], *stems: str) -> bool:
    return any(word.startswith(stem) for word in words for stem in stems)


def _has_research_action(normalized: str) -> bool:
    return re.search(
        r"(?:^| )(?:"
        r"arastir(?:in|alim|abilir|abiliriz)?|"
        r"karsilastir(?:in|alim|abilir|abiliriz)?|"
        r"research|investigate|compare"
        r")(?: |$)",
        normalized,
    ) is not None


def _safe_text(value: object, label: str, maximum_bytes: int) -> str:
    if not isinstance(value, str):
        raise ResearchIntentError(f"{label} must be text")
    result = unicodedata.normalize("NFC", value).strip()
    if (
        not result
        or len(result.encode("utf-8")) > maximum_bytes
        or CONTROL.search(result)
        or SECRET.search(result)
        or WINDOWS_PATH.search(result)
        or POSIX_PATH.search(result)
    ):
        raise ResearchIntentError(f"{label} is invalid, sensitive, or path-bearing")
    return result


def _topic_missing(normalized: str, policy: Mapping[str, object]) -> bool:
    remaining = normalized
    phrases = list(policy["explicit_research_phrases"])
    phrases.extend(policy["project_references"])
    phrases.extend(policy["context_references"])
    for collection in dict(policy["mode_markers"]).values():
        phrases.extend(collection)
    for collection in dict(policy["outcome_markers"]).values():
        phrases.extend(collection)
    for phrase in sorted(set(phrases), key=len, reverse=True):
        remaining = re.sub(rf"(?:^| )({re.escape(phrase)})(?= |$)", " ", remaining)
    words = set(remaining.split())
    return not words or words.issubset(DEICTIC_WORDS)


@dataclass(frozen=True)
class ResearchIntent:
    mode: str
    outcome: str
    objective: str
    project_id: str | None
    needs_context: bool
    scope_preference: str
    needs_project: bool
    request_digest: str
    intent_digest: str
    context: str | None = None

    def public_summary(self) -> dict[str, object]:
        next_action = (
            "select-project" if self.needs_project
            else "provide-context" if self.needs_context
            else "prepare-research"
        )
        return {
            "schema_ref": "schemas/research-intent-result.schema.json",
            "schema_version": 1,
            "request_sha256": self.request_digest,
            "intent_sha256": self.intent_digest,
            "objective_sha256": hashlib.sha256(self.objective.encode("utf-8")).hexdigest(),
            "mode": self.mode,
            "outcome": self.outcome,
            "scope_preference": self.scope_preference,
            "project_id": self.project_id,
            "needs_context": self.needs_context,
            "needs_project": self.needs_project,
            "status": "needs-context" if self.needs_context else "ready",
            "next_action": next_action,
            "authority_granted": False,
            "mutation_authorized": False,
            "provider_authorized": False,
            "raw_request_included": False,
            "physical_paths_included": False,
            "credential_values_included": False,
        }

    def research_request(self) -> dict[str, object]:
        if self.needs_context:
            raise ResearchIntentError("research request needs context before preparation")
        scope = "project" if self.project_id is not None else "global"
        identity = {
            "mode": self.mode,
            "outcome": self.outcome,
            "objective": self.objective,
            "project_id": self.project_id,
            "context": self.context,
        }
        request = {
            "schema_ref": "schemas/research-run-request.schema.json",
            "schema_version": 1,
            "research_id": "research-" + _digest(identity)[:24],
            "scope": scope,
            "title": f"{self.mode} {self.outcome} research",
            "objective": self.objective,
            "acceptance_criteria": [
                f"Use the {self.mode} research depth and preserve evidence links.",
                f"Produce the {self.outcome} outcome without granting mutation or provider authority.",
                "Keep conflicts visible and require separate approval for any implementation.",
            ],
        }
        if self.project_id is not None:
            request["project_id"] = self.project_id
        if self.context and self.context != self.objective:
            request["context"] = self.context
        return request


def parse_research_intent(
    repo_root: Path,
    request_text: str,
    *,
    project_id: str | None = None,
    context_text: str | None = None,
) -> ResearchIntent | None:
    """Return an intent only for an explicit Turkish or English research action."""

    policy = _load_policy(repo_root)
    if not isinstance(request_text, str):
        raise ResearchIntentError("research intent request must be text")
    raw = unicodedata.normalize("NFC", request_text).strip()
    if not raw or len(raw.encode("utf-8")) > int(policy["max_request_bytes"]):
        raise ResearchIntentError("research intent request is empty or too large")
    normalized = _normalized(raw)
    if RESERVED_LIFECYCLE.fullmatch(normalized):
        return None
    words = set(normalized.split())
    explicit = _has_research_action(normalized) or _any_phrase(
        normalized, tuple(policy["explicit_research_phrases"])
    )
    if not explicit:
        return None
    request = _safe_text(raw, "research intent request", int(policy["max_request_bytes"]))
    if project_id is not None and (not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id)):
        raise ResearchIntentError("research intent project id is invalid")
    context = (
        _safe_text(context_text, "research intent context", int(policy["max_request_bytes"]))
        if context_text is not None
        else None
    )
    if (
        _any_phrase(normalized, tuple(dict(policy["mode_markers"])["root-cause"]))
        or ("kok" in words and _has_stem(words, "neden", "sebep"))
    ):
        mode = "root-cause"
    elif (
        _any_phrase(normalized, tuple(dict(policy["mode_markers"])["comparison"]))
        or _has_stem(words, "karsilastir")
    ):
        mode = "comparison"
    elif (
        _any_phrase(normalized, tuple(dict(policy["mode_markers"])["deep"]))
        or _has_stem(words, "detayli", "derinlemesine", "kapsamli")
    ):
        mode = "deep"
    elif (
        _any_phrase(normalized, tuple(dict(policy["mode_markers"])["quick"]))
        or _has_stem(words, "hizli", "kisa")
    ):
        mode = "quick"
    else:
        mode = "standard"
    outcome = "research-only"
    for candidate in ("research-and-implement", "research-and-plan"):
        if _any_phrase(normalized, tuple(dict(policy["outcome_markers"])[candidate])):
            outcome = candidate
            break
    if _has_stem(words, "arastir") and _has_stem(words, "uygula", "gelistir", "duzelt"):
        outcome = "research-and-implement"
    elif _has_stem(words, "arastir") and _has_stem(words, "planla"):
        outcome = "research-and-plan"
    explicit_project = (
        _any_phrase(normalized, tuple(policy["project_references"]))
        or bool(words.intersection(PROJECT_WORDS))
    )
    needs_project = explicit_project and project_id is None
    deictic = _any_phrase(normalized, tuple(policy["context_references"]))
    missing_topic = _topic_missing(normalized, policy)
    generic_reference = (
        bool(words.intersection({"bu", "su", "this", "that"}))
        and bool(words.intersection(GENERIC_REFERENTS))
        and not explicit_project
    )
    incomplete_comparison = (
        mode == "comparison"
        and not words.intersection(COMPARISON_CONNECTORS)
    )
    contextual_subject_required = (
        missing_topic or generic_reference or incomplete_comparison
    )
    unresolved_reference = contextual_subject_required and context is None
    needs_context = needs_project or unresolved_reference
    objective = (
        context
        if contextual_subject_required and context is not None
        else request
    )
    scope_preference = "project" if explicit_project else "auto" if project_id is not None else "global"
    request_digest = hashlib.sha256(request.encode("utf-8")).hexdigest()
    identity = {
        "mode": mode,
        "outcome": outcome,
        "objective_sha256": hashlib.sha256(objective.encode("utf-8")).hexdigest(),
        "project_id": project_id,
        "needs_context": needs_context,
        "scope_preference": scope_preference,
        "needs_project": needs_project,
        "request_digest": request_digest,
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest() if context else None,
    }
    return ResearchIntent(
        mode, outcome, objective, project_id, needs_context, scope_preference,
        needs_project, request_digest, _digest(identity), context,
    )

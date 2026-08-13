"""Deterministic, read-only classification of legacy mk-hub work trees."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping

from .work_graph import IDENTIFIER
from .work_import import WorkImportError, WorkSourceInventory, inventory_work_source


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "legacy-work-classifier.json"
NUMERIC_GROUP = re.compile(r"^[0-9]+(?:_[0-9]+)*$")
VARIANT_GROUP = re.compile(r"^([0-9]+)_[0-9]+$")


class LegacyWorkClassifierError(ValueError):
    """Raised when a legacy tree cannot be classified safely."""


def _portable_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = "item-" + slug
    return slug


def _load_policy(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyWorkClassifierError("legacy work classifier policy is unavailable") from exc
    expected = {
        "schema_ref", "schema_version", "source_id", "logical_root", "buckets",
        "category_prefixes", "task_extensions", "task_id_pattern",
        "combined_relation_type",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise LegacyWorkClassifierError("legacy work classifier policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/legacy-work-classifier-policy.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise LegacyWorkClassifierError("legacy work classifier policy header is invalid")
    if not isinstance(payload.get("source_id"), str) or not IDENTIFIER.fullmatch(payload["source_id"]):
        raise LegacyWorkClassifierError("legacy work classifier source id is invalid")
    if not isinstance(payload.get("logical_root"), str):
        raise LegacyWorkClassifierError("legacy work classifier logical root is invalid")
    if not isinstance(payload.get("buckets"), dict) or not isinstance(payload.get("category_prefixes"), dict):
        raise LegacyWorkClassifierError("legacy work classifier mappings are invalid")
    if not isinstance(payload.get("task_extensions"), list):
        raise LegacyWorkClassifierError("legacy work classifier extensions are invalid")
    try:
        re.compile(str(payload.get("task_id_pattern")))
    except re.error as exc:
        raise LegacyWorkClassifierError("legacy work classifier task pattern is invalid") from exc
    return payload


@dataclass(frozen=True)
class ClassificationReview:
    code: str
    external_id: str | None
    source_refs: tuple[str, ...]
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "external_id": self.external_id,
            "source_refs": list(self.source_refs),
            "message": self.message,
        }


@dataclass
class _CandidateDraft:
    work_item_id: str
    work_type: str
    external_id: str
    source_bucket: str
    status: str
    title: str
    source_refs: set[str] = field(default_factory=set)
    relations: set[tuple[str, str]] = field(default_factory=set)

    def as_import_candidate(self, entries: Mapping[str, tuple[str, int]]) -> dict[str, object]:
        refs = sorted(self.source_refs)
        if not refs:
            raise LegacyWorkClassifierError("classified work candidate has no source evidence")
        evidence = [
            {
                "evidence_type": "document",
                "reference": ref,
                "digest": entries[ref][0],
                "label": PurePosixPath(ref).name,
            }
            for ref in refs
        ]
        return {
            "work_item_id": self.work_item_id,
            "work_type": self.work_type,
            "title": self.title,
            "description": f"Legacy source bucket: {self.source_bucket}.",
            "status": self.status,
            "acceptance_criteria": [],
            "relations": [
                {"relation_type": relation_type, "target_ref": target_ref}
                for relation_type, target_ref in sorted(self.relations)
            ],
            "evidence": evidence,
            "source_ref": refs[0],
        }


@dataclass(frozen=True)
class LegacyWorkClassification:
    project_id: str
    source_inventory: WorkSourceInventory
    candidates: tuple[Mapping[str, object], ...]
    reviews: tuple[ClassificationReview, ...]
    bucket_statuses: Mapping[str, str] = field(repr=False)

    @property
    def import_ready(self) -> bool:
        return bool(self.candidates) and not self.reviews

    def work_import_request(self) -> dict[str, object]:
        if not self.import_ready:
            raise LegacyWorkClassifierError("legacy work classification requires review")
        return {
            "schema_ref": "schemas/work-import-request.schema.json",
            "schema_version": 1,
            "project_id": self.project_id,
            "source_inventory": self.source_inventory.as_dict(),
            "candidates": [dict(candidate) for candidate in self.candidates],
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/legacy-work-classification.schema.json",
            "schema_version": 1,
            "project_id": self.project_id,
            "source_inventory": self.source_inventory.public_summary(),
            "candidate_count": len(self.candidates),
            "reviews": [review.as_dict() for review in self.reviews],
            "import_ready": self.import_ready,
            "work_import_request": self.work_import_request() if self.import_ready else None,
            "paths_disclosed": False,
        }


@dataclass(frozen=True)
class ConflictSplitSummary:
    external_id: str
    work_item_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "external_id": self.external_id,
            "variant_count": len(self.work_item_ids),
            "work_item_ids": list(self.work_item_ids),
        }


@dataclass(frozen=True)
class LegacyWorkReviewResolution:
    project_id: str
    source_inventory: WorkSourceInventory
    candidates: tuple[Mapping[str, object], ...]
    unresolved_reviews: tuple[ClassificationReview, ...]
    splits: tuple[ConflictSplitSummary, ...]

    @property
    def import_ready(self) -> bool:
        return bool(self.candidates) and not self.unresolved_reviews

    def work_import_request(self) -> dict[str, object]:
        if not self.import_ready:
            raise LegacyWorkClassifierError("legacy work review resolution is incomplete")
        return {
            "schema_ref": "schemas/work-import-request.schema.json",
            "schema_version": 1,
            "project_id": self.project_id,
            "source_inventory": self.source_inventory.as_dict(),
            "candidates": [dict(candidate) for candidate in self.candidates],
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/legacy-work-review-resolution.schema.json",
            "schema_version": 1,
            "project_id": self.project_id,
            "decision": "split-conflicts",
            "resolved_identity_count": len(self.splits),
            "splits": [split.as_dict() for split in self.splits],
            "unresolved_review_count": len(self.unresolved_reviews),
            "import_ready": self.import_ready,
            "paths_disclosed": False,
        }


def _reference_bucket(reference: str, logical_root: str) -> str:
    prefix = logical_root.rstrip("/") + "/"
    if not reference.startswith(prefix):
        raise LegacyWorkClassifierError("review source reference is outside its inventory")
    remainder = reference[len(prefix):]
    parts = PurePosixPath(remainder).parts
    if not parts:
        raise LegacyWorkClassifierError("review source reference has no source bucket")
    return parts[0].casefold()


def resolve_legacy_work_reviews(
    classification: LegacyWorkClassification,
    *,
    decision: str,
) -> LegacyWorkReviewResolution:
    """Resolve task identity conflicts only after an explicit split decision."""

    if decision != "split-conflicts":
        raise LegacyWorkClassifierError("legacy work review resolution decision is unsupported")
    conflict_refs: dict[str, set[str]] = {}
    unresolved: list[ClassificationReview] = []
    for review in classification.reviews:
        if review.code != "conflicting-task-id" or not review.external_id:
            unresolved.append(review)
            continue
        conflict_refs.setdefault(review.external_id, set()).update(review.source_refs)
    entry_by_ref = {
        entry.source_ref: (entry.sha256, entry.size_bytes)
        for entry in classification.source_inventory.entries
    }
    candidates = {
        str(candidate["work_item_id"]): dict(candidate)
        for candidate in classification.candidates
    }
    splits: list[ConflictSplitSummary] = []
    for external_id, refs in sorted(conflict_refs.items()):
        base_id = f"{classification.project_id}-task-{_portable_slug(external_id)}"
        candidates.pop(base_id, None)
        variants: list[str] = []
        for reference in sorted(refs):
            entry = entry_by_ref.get(reference)
            if entry is None:
                raise LegacyWorkClassifierError("review source reference is absent from inventory")
            digest = entry[0]
            bucket = _reference_bucket(reference, classification.source_inventory.logical_root)
            status = classification.bucket_statuses.get(bucket)
            if status is None:
                raise LegacyWorkClassifierError("review source bucket is not classified")
            file_name = PurePosixPath(reference).name
            file_slug = _portable_slug(PurePosixPath(reference).stem)[:48].rstrip("-")
            variant_id = (
                f"{base_id}-variant-{_portable_slug(bucket)}-{file_slug}-{digest[:12]}"
            )
            if variant_id in candidates:
                raise LegacyWorkClassifierError("split conflict variant identity is duplicated")
            draft = _CandidateDraft(
                variant_id,
                "task",
                external_id,
                bucket,
                status,
                f"Task {external_id} variant: {file_name}",
                {reference},
                set(),
            )
            candidate = draft.as_import_candidate(entry_by_ref)
            candidate["description"] = (
                f"Legacy task identity {external_id}; source bucket: {bucket}; "
                "kept as a separate reviewed variant."
            )
            candidates[variant_id] = candidate
            variants.append(variant_id)
        splits.append(ConflictSplitSummary(external_id, tuple(variants)))
    return LegacyWorkReviewResolution(
        classification.project_id,
        classification.source_inventory,
        tuple(candidates[key] for key in sorted(candidates)),
        tuple(sorted(unresolved, key=lambda value: (value.code, value.external_id or "", value.source_refs))),
        tuple(splits),
    )

def _category_type(name: str, prefixes: Mapping[str, object]) -> str | None:
    prefix = name.split("_", 1)[0].casefold()
    for configured, work_type in prefixes.items():
        if prefix == str(configured).casefold():
            return str(work_type)
    return None


def _group_external_ids(name: str) -> tuple[str, ...]:
    if not NUMERIC_GROUP.fullmatch(name):
        return ()
    parts = tuple(name.split("_"))
    if len(parts) == 2 and VARIANT_GROUP.fullmatch(name) and len(parts[1]) <= 2:
        return (parts[0],)
    return parts


def classify_legacy_work_source(
    source_root: Path,
    *,
    project_id: str,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> LegacyWorkClassification:
    """Classify structure and file metadata without retaining physical paths or contents."""

    if not IDENTIFIER.fullmatch(project_id):
        raise LegacyWorkClassifierError("legacy work project id is invalid")
    policy = _load_policy(policy_path)
    try:
        inventory = inventory_work_source(
            source_root,
            source_id=str(policy["source_id"]),
            logical_root=str(policy["logical_root"]),
        )
    except WorkImportError as exc:
        raise LegacyWorkClassifierError(str(exc)) from exc
    root = source_root.resolve(strict=True)
    logical_root = inventory.logical_root.rstrip("/")
    entry_by_relative = {
        entry.source_ref[len(logical_root) + 1:]: (entry.sha256, entry.size_bytes)
        for entry in inventory.entries
    }
    entry_by_ref = {
        entry.source_ref: (entry.sha256, entry.size_bytes) for entry in inventory.entries
    }
    drafts: dict[str, _CandidateDraft] = {}
    reviews: list[ClassificationReview] = []
    buckets = {str(key).casefold(): str(value) for key, value in policy["buckets"].items()}
    prefixes = policy["category_prefixes"]
    relation_type = str(policy["combined_relation_type"])

    for bucket_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
        bucket = bucket_dir.name.casefold()
        status = buckets.get(bucket)
        if status is None:
            continue
        for category_dir in sorted((path for path in bucket_dir.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
            work_type = _category_type(category_dir.name, prefixes)
            if work_type is None:
                continue
            combined: list[tuple[tuple[str, ...], set[str]]] = []
            for group_dir in sorted((path for path in category_dir.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
                ids = _group_external_ids(group_dir.name)
                if not ids:
                    ids = (_portable_slug(group_dir.name),)
                refs = {
                    f"{logical_root}/{path.relative_to(root).as_posix()}"
                    for path in group_dir.rglob("*") if path.is_file()
                }
                if not refs:
                    continue
                if len(ids) > 1:
                    combined.append((ids, refs))
                for external_id in ids:
                    item_id = f"{project_id}-{work_type}-{_portable_slug(external_id)}"
                    draft = drafts.get(item_id)
                    if draft is None:
                        draft = _CandidateDraft(
                            item_id, work_type, external_id, bucket, status,
                            f"{work_type.capitalize()} {external_id}",
                        )
                        drafts[item_id] = draft
                    elif draft.work_type != work_type or draft.source_bucket != bucket:
                        reviews.append(ClassificationReview(
                            "unclassified-entry", external_id, tuple(sorted(refs)),
                            "The same legacy identity appears in incompatible buckets or categories.",
                        ))
                    draft.source_refs.update(refs)
            for ids, refs in combined:
                targets = [f"{project_id}-{work_type}-{_portable_slug(value)}" for value in ids]
                for target in targets:
                    drafts[target].source_refs.update(refs)
                    drafts[target].relations.update(
                        (relation_type, peer) for peer in targets if peer != target
                    )

        task_pattern = re.compile(str(policy["task_id_pattern"]), re.IGNORECASE)
        extensions = {str(value).casefold() for value in policy["task_extensions"]}
        task_sources: dict[str, list[str]] = {}
        for path in sorted((path for path in bucket_dir.iterdir() if path.is_file()), key=lambda path: path.name.casefold()):
            if path.suffix.casefold() not in extensions:
                continue
            match = task_pattern.search(path.name)
            if match:
                task_sources.setdefault(match.group(1).upper(), []).append(
                    f"{logical_root}/{path.relative_to(root).as_posix()}"
                )
        for external_id, refs in sorted(task_sources.items()):
            if len(refs) > 1:
                reviews.append(ClassificationReview(
                    "conflicting-task-id", external_id, tuple(sorted(refs)),
                    "Multiple legacy task files claim the same task identity.",
                ))
                continue
            item_id = f"{project_id}-task-{_portable_slug(external_id)}"
            if item_id in drafts:
                previous_refs = drafts[item_id].source_refs
                reviews.append(ClassificationReview(
                    "conflicting-task-id", external_id,
                    tuple(sorted(previous_refs | set(refs))),
                    "A legacy task identity collides with another classified item.",
                ))
                continue
            drafts[item_id] = _CandidateDraft(
                item_id, "task", external_id, bucket, status,
                f"Task {external_id}", set(refs), set(),
            )

    candidates = tuple(
        drafts[key].as_import_candidate(entry_by_ref)
        for key in sorted(drafts)
    )
    return LegacyWorkClassification(
        project_id, inventory, candidates,
        tuple(sorted(reviews, key=lambda value: (value.code, value.external_id or "", value.source_refs))),
        buckets,
    )

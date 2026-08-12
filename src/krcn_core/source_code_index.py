"""Contentless, incremental source-code vectors over read-only project bindings."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .adapter_gate import (
    AdapterAuthorization,
    AdapterDescriptor,
    AdapterOperation,
)
from .discovery import DiscoveryResult, FileEvidence
from .embedding_models import load_embedding_model_catalog
from .foundation import load_json
from .information_records import canonical_json
from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .source_bindings import SourceBinding


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
TOKEN = re.compile(r"\w+", re.UNICODE)
SAFE_SYMBOL = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.-]{0,127}$")
MAX_QUERY_LENGTH = 4096
MAX_RESULT_LIMIT = 50
INDEX_DIRECTORY_REF = ".krcn/derived/retrieval/source-code-v1"
WEIGHTS = {"exact": 0.35, "fts": 0.25, "vector": 0.40}

LANGUAGE_BY_EXTENSION = {
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".gradle": "gradle",
    ".graphql": "graphql",
    ".groovy": "groovy",
    ".h": "c-header",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascript-react",
    ".jrxml": "xml",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".md": "markdown",
    ".php": "php",
    ".properties": "properties",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".scss": "scss",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}
LANGUAGE_BY_FILENAME = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
}

LOCAL_SOURCE_CODE_ADAPTER = AdapterDescriptor(
    adapter_id="local-source-code",
    version="1.0.0",
    source_kinds=("project",),
    resource_type="source",
    operations=(
        AdapterOperation("index", ("read", "metadata"), "allow", False, False),
        AdapterOperation("retrieve", ("read", "metadata"), "allow", False, False),
    ),
)


class SourceCodeIndexError(ValueError):
    """Raised when source-code indexing or retrieval is unsafe or stale."""


@dataclass(frozen=True)
class SourceCodeIndexPolicy:
    index_revision: int
    offline_embedding_profile_id: str
    vector_dimensions: int
    chunk_target_lines: int
    chunk_overlap_lines: int
    maximum_chunk_characters: int
    maximum_indexed_file_bytes: int
    maximum_chunks: int
    maximum_search_content_characters: int
    supported_extensions: tuple[str, ...]
    supported_filenames: tuple[str, ...]
    policy_digest: str


@dataclass(frozen=True)
class SourceCodeChunk:
    chunk_id: str
    relative_path: str
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    content_sha256: str
    language: str
    symbols: tuple[str, ...]
    vector: tuple[float, ...]


@dataclass(frozen=True)
class IndexedCodeFile:
    relative_path: str
    content_sha256: str
    size: int
    language: str
    chunks: tuple[SourceCodeChunk, ...]


@dataclass(frozen=True)
class SourceCodeIndexPlan:
    project_id: str
    binding_id: str
    binding_revision: int
    source_root: Path
    source_digest: str
    policy_digest: str
    embedding_profile_id: str
    vector_dimensions: int
    files: tuple[IndexedCodeFile, ...]
    processed_file_count: int
    reused_file_count: int
    removed_file_count: int
    skipped: Mapping[str, int]
    index_digest: str
    mutation: MutationPlan

    @property
    def plan_id(self) -> str:
        return self.mutation.plan_id

    @property
    def chunk_count(self) -> int:
        return sum(len(item.chunks) for item in self.files)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/source-code-index-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "source_digest": self.source_digest,
            "policy_digest": self.policy_digest,
            "index_digest": self.index_digest,
            "embedding_profile_id": self.embedding_profile_id,
            "vector_dimensions": self.vector_dimensions,
            "selected_file_count": len(self.files),
            "processed_file_count": self.processed_file_count,
            "reused_file_count": self.reused_file_count,
            "removed_file_count": self.removed_file_count,
            "chunk_count": self.chunk_count,
            "skipped": dict(self.skipped),
            "mutation": self.mutation.as_dict(),
            "incremental": True,
            "source_access": "read-only",
            "source_copy": False,
            "source_content_persisted": False,
            "remote_provider_used": False,
        }


@dataclass(frozen=True)
class SourceCodeQuery:
    query_id: str
    project_id: str
    text: str
    languages: tuple[str, ...]
    path_prefix: str | None
    include_content: bool
    limit: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/source-code-query.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "project_id": self.project_id,
            "text": self.text,
            "languages": list(self.languages),
            "path_prefix": self.path_prefix,
            "include_content": self.include_content,
            "limit": self.limit,
        }

    @property
    def query_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


def load_source_code_index_policy(repo_root: Path) -> SourceCodeIndexPolicy:
    payload = load_json(repo_root / "config" / "source-code-index.json")
    expected = {
        "schema_ref",
        "schema_version",
        "enabled",
        "index_revision",
        "offline_embedding_profile_id",
        "vector_dimensions",
        "chunk_target_lines",
        "chunk_overlap_lines",
        "maximum_chunk_characters",
        "maximum_indexed_file_bytes",
        "maximum_chunks",
        "maximum_search_content_characters",
        "supported_extensions",
        "supported_filenames",
        "source_content_persisted",
        "remote_provider_implicit",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_ref")
        != "schemas/source-code-index-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("enabled") is not True
        or payload.get("index_revision") != 1
        or payload.get("offline_embedding_profile_id") != "deterministic-hashing"
        or payload.get("vector_dimensions") != 192
        or payload.get("source_content_persisted") is not False
        or payload.get("remote_provider_implicit") is not False
    ):
        raise SourceCodeIndexError("source code index policy is invalid")
    integer_fields = {
        "chunk_target_lines": (20, 1000),
        "chunk_overlap_lines": (0, 200),
        "maximum_chunk_characters": (1000, 100000),
        "maximum_indexed_file_bytes": (1000, 10000000),
        "maximum_chunks": (1, 1000000),
        "maximum_search_content_characters": (1000, 1000000),
    }
    values: dict[str, int] = {}
    for field, (minimum, maximum) in integer_fields.items():
        value = payload.get(field)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not minimum <= value <= maximum
        ):
            raise SourceCodeIndexError(f"source code index {field} is invalid")
        values[field] = value
    if values["chunk_overlap_lines"] >= values["chunk_target_lines"]:
        raise SourceCodeIndexError("source code chunk overlap must be below target")
    extensions = payload.get("supported_extensions")
    filenames = payload.get("supported_filenames")
    if (
        not isinstance(extensions, list)
        or not extensions
        or any(
            not isinstance(item, str)
            or item != item.lower()
            or not re.fullmatch(r"\.[a-z0-9]+", item)
            for item in extensions
        )
        or len(set(extensions)) != len(extensions)
        or tuple(extensions) != tuple(sorted(extensions))
        or not isinstance(filenames, list)
        or any(
            not isinstance(item, str)
            or item != item.lower()
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", item)
            for item in filenames
        )
        or len(set(filenames)) != len(filenames)
        or tuple(filenames) != tuple(sorted(filenames))
    ):
        raise SourceCodeIndexError("source code supported file policy is invalid")
    if any(item not in LANGUAGE_BY_EXTENSION for item in extensions) or any(
        item not in LANGUAGE_BY_FILENAME for item in filenames
    ):
        raise SourceCodeIndexError("source code language mapping is incomplete")
    catalog = load_embedding_model_catalog(repo_root)
    if payload["offline_embedding_profile_id"] != catalog.offline_fallback_id:
        raise SourceCodeIndexError("source code and embedding policies disagree")
    policy_digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    return SourceCodeIndexPolicy(
        index_revision=1,
        offline_embedding_profile_id="deterministic-hashing",
        vector_dimensions=192,
        chunk_target_lines=values["chunk_target_lines"],
        chunk_overlap_lines=values["chunk_overlap_lines"],
        maximum_chunk_characters=values["maximum_chunk_characters"],
        maximum_indexed_file_bytes=values["maximum_indexed_file_bytes"],
        maximum_chunks=values["maximum_chunks"],
        maximum_search_content_characters=values[
            "maximum_search_content_characters"
        ],
        supported_extensions=tuple(extensions),
        supported_filenames=tuple(filenames),
        policy_digest=policy_digest,
    )


def _normalized_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(TOKEN.findall(normalized))


def _features(value: str) -> tuple[str, ...]:
    tokens = _normalized_tokens(value)
    features = list(tokens)
    for token in tokens:
        padded = f"^{token}$"
        features.extend(
            f"g:{padded[index:index + 3]}"
            for index in range(max(0, len(padded) - 2))
        )
    return tuple(features)


def _vector(value: str, dimensions: int) -> tuple[float, ...]:
    values = [0.0] * dimensions
    for feature in _features(value):
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in values))
    if norm:
        values = [item / norm for item in values]
    return tuple(float(f"{item:.12f}") for item in values)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise SourceCodeIndexError("source code vector dimensions are invalid")
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def _language(relative_path: str, policy: SourceCodeIndexPolicy) -> str | None:
    path = PurePosixPath(relative_path)
    extension = path.suffix.lower()
    if extension in policy.supported_extensions:
        return LANGUAGE_BY_EXTENSION[extension]
    name = path.name.lower()
    if name in policy.supported_filenames:
        return LANGUAGE_BY_FILENAME[name]
    return None


def _safe_source_file(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SourceCodeIndexError("source code relative path is unsafe")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise SourceCodeIndexError("source code path may not use symbolic links")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SourceCodeIndexError("source code path escapes the project root") from exc
    if not resolved.is_file():
        raise SourceCodeIndexError("source code path is not a regular file")
    return resolved


def _read_verified_text(
    root: Path,
    evidence: FileEvidence,
) -> str:
    source = _safe_source_file(root, evidence.relative_path)
    before = source.stat(follow_symlinks=False)
    content = source.read_bytes()
    after = source.stat(follow_symlinks=False)
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or after.st_size != evidence.size
        or hashlib.sha256(content).hexdigest() != evidence.sha256
    ):
        raise SourceCodeIndexError(
            "source file changed after discovery: "
            f"{evidence.relative_path}; reintegrate the project"
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceCodeIndexError("source file is not valid UTF-8") from exc
    if "\x00" in text:
        raise SourceCodeIndexError("source file contains binary content")
    return text


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    if starts[-1] == len(text) and len(starts) > 1:
        starts.pop()
    return tuple(starts)


def _natural_boundary(line: str) -> bool:
    stripped = line.strip()
    return bool(
        not stripped
        or re.match(
            r"(?:public|protected|private|internal|export|async|static|final|abstract|class|interface|enum|record|function|def|CREATE)\b",
            stripped,
            re.IGNORECASE,
        )
    )


def _chunk_ranges(
    text: str,
    policy: SourceCodeIndexPolicy,
) -> tuple[tuple[int, int, int, int], ...]:
    if not text:
        return ()
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [text]
    starts = []
    position = 0
    for line in lines:
        starts.append(position)
        position += len(line)
    ranges: list[tuple[int, int, int, int]] = []
    start_index = 0
    while start_index < len(lines):
        line_length = len(lines[start_index])
        if line_length > policy.maximum_chunk_characters:
            line_start = starts[start_index]
            line_end = line_start + line_length
            segment_start = line_start
            while segment_start < line_end:
                segment_end = min(
                    segment_start + policy.maximum_chunk_characters,
                    line_end,
                )
                ranges.append(
                    (
                        segment_start,
                        segment_end,
                        start_index + 1,
                        start_index + 1,
                    )
                )
                segment_start = segment_end
            start_index += 1
            continue
        end_index = min(
            start_index + policy.chunk_target_lines,
            len(lines),
        )
        lower_boundary = min(
            end_index,
            start_index + max(1, policy.chunk_target_lines * 2 // 3),
        )
        if end_index < len(lines):
            for candidate in range(end_index, lower_boundary, -1):
                if _natural_boundary(lines[candidate]):
                    end_index = candidate
                    break
        while end_index > start_index + 1:
            end_offset = starts[end_index] if end_index < len(lines) else len(text)
            if end_offset - starts[start_index] <= policy.maximum_chunk_characters:
                break
            end_index -= 1
        start_offset = starts[start_index]
        end_offset = starts[end_index] if end_index < len(lines) else len(text)
        ranges.append((start_offset, end_offset, start_index + 1, end_index))
        if end_index >= len(lines):
            break
        next_index = max(
            start_index + 1,
            end_index - policy.chunk_overlap_lines,
        )
        start_index = next_index
    return tuple(ranges)


def _symbols(text: str, language: str) -> tuple[str, ...]:
    patterns = [
        r"\b(?:class|interface|enum|record|trait|struct|type|module|namespace)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        r"\b(?:function|def|func|fn)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    ]
    if language in {"java", "csharp", "kotlin", "typescript", "typescript-react"}:
        patterns.append(
            r"(?m)^\s*(?:public|protected|private|internal|static|final|abstract|async|override|open|suspend|\s)+[A-Za-z_$][A-Za-z0-9_$<>,.?\[\] ]*\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
        )
    if language == "sql":
        patterns.append(
            r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|FUNCTION|PROCEDURE|TRIGGER|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_$][A-Za-z0-9_$.-]*)"
        )
    if language in {"properties", "yaml", "toml"}:
        patterns.append(r"(?m)^\s*([A-Za-z_$][A-Za-z0-9_$.-]*)\s*[:=]")
    if language in {"xml", "html", "vue"}:
        patterns.append(r"<([A-Za-z_$][A-Za-z0-9_$.-]*)\b")
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1)
            if SAFE_SYMBOL.fullmatch(value) and value not in seen:
                seen.add(value)
                found.append(value)
                if len(found) >= 64:
                    return tuple(found)
    return tuple(found)


def _build_file(
    project_id: str,
    root: Path,
    evidence: FileEvidence,
    language: str,
    policy: SourceCodeIndexPolicy,
) -> IndexedCodeFile:
    text = _read_verified_text(root, evidence)
    chunks = []
    for start_offset, end_offset, start_line, end_line in _chunk_ranges(text, policy):
        content = text[start_offset:end_offset]
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        symbols = _symbols(content, language)
        vector_text = " ".join(
            (
                project_id,
                evidence.relative_path,
                language,
                " ".join(symbols),
                content,
            )
        )
        identity = {
            "project_id": project_id,
            "relative_path": evidence.relative_path,
            "file_sha256": evidence.sha256,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "start_line": start_line,
            "end_line": end_line,
            "content_sha256": content_sha256,
        }
        chunk_id = hashlib.sha256(canonical_json(identity)).hexdigest()
        chunks.append(
            SourceCodeChunk(
                chunk_id,
                evidence.relative_path,
                start_line,
                end_line,
                start_offset,
                end_offset,
                content_sha256,
                language,
                symbols,
                _vector(vector_text, policy.vector_dimensions),
            )
        )
    return IndexedCodeFile(
        evidence.relative_path,
        evidence.sha256,
        evidence.size,
        language,
        tuple(chunks),
    )


def source_code_index_path(data_root: Path, project_id: str) -> Path:
    if not IDENTIFIER.fullmatch(project_id):
        raise SourceCodeIndexError("source code project id is invalid")
    return (
        data_root.resolve()
        / "derived"
        / "retrieval"
        / "source-code-v1"
        / f"{project_id}.sqlite"
    )


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(connection.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.Error as exc:
        raise SourceCodeIndexError("source code index metadata is invalid") from exc


def _load_existing_files(
    target: Path,
    *,
    project_id: str,
    binding_id: str,
    policy: SourceCodeIndexPolicy,
) -> tuple[bool, dict[str, IndexedCodeFile]]:
    if not target.is_file() or target.is_symlink():
        return False, {}
    try:
        connection = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            metadata = _metadata(connection)
            if (
                metadata.get("index_revision") != str(policy.index_revision)
                or metadata.get("project_id") != project_id
                or metadata.get("binding_id") != binding_id
                or metadata.get("policy_digest") != policy.policy_digest
                or metadata.get("embedding_profile_id")
                != policy.offline_embedding_profile_id
                or metadata.get("vector_dimensions")
                != str(policy.vector_dimensions)
                or metadata.get("source_content_persisted") != "false"
                or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                return False, {}
            file_rows = connection.execute(
                "SELECT relative_path, content_sha256, size, language, chunk_count FROM files"
            ).fetchall()
            chunk_rows = connection.execute(
                "SELECT chunk_id, relative_path, start_line, end_line, start_offset, end_offset, content_sha256, language, symbols_json, vector_json FROM chunks ORDER BY relative_path, start_offset, chunk_id"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error, SourceCodeIndexError):
        return False, {}
    chunks_by_path: dict[str, list[SourceCodeChunk]] = {}
    try:
        for row in chunk_rows:
            symbols_payload = json.loads(row[8])
            vector_payload = json.loads(row[9])
            if (
                not isinstance(symbols_payload, list)
                or any(
                    not isinstance(item, str) or not SAFE_SYMBOL.fullmatch(item)
                    for item in symbols_payload
                )
                or not isinstance(vector_payload, list)
                or len(vector_payload) != policy.vector_dimensions
                or any(
                    not isinstance(item, (int, float)) or not math.isfinite(item)
                    for item in vector_payload
                )
            ):
                return False, {}
            chunk = SourceCodeChunk(
                str(row[0]),
                str(row[1]),
                int(row[2]),
                int(row[3]),
                int(row[4]),
                int(row[5]),
                str(row[6]),
                str(row[7]),
                tuple(symbols_payload),
                tuple(float(item) for item in vector_payload),
            )
            chunks_by_path.setdefault(chunk.relative_path, []).append(chunk)
        files = {}
        for relative_path, digest, size, language, chunk_count in file_rows:
            chunks = tuple(chunks_by_path.get(str(relative_path), []))
            if len(chunks) != int(chunk_count):
                return False, {}
            files[str(relative_path)] = IndexedCodeFile(
                str(relative_path),
                str(digest),
                int(size),
                str(language),
                chunks,
            )
        if set(chunks_by_path) - set(files):
            return False, {}
        source_digest = metadata.get("source_digest")
        binding_revision = metadata.get("binding_revision")
        if (
            not isinstance(source_digest, str)
            or not SHA256.fullmatch(source_digest)
            or not isinstance(binding_revision, str)
            or not binding_revision.isdigit()
            or int(binding_revision) < 1
        ):
            return False, {}
        files_tuple = tuple(sorted(files.values(), key=lambda item: item.relative_path))
        identity = _index_identity(
            project_id,
            binding_id,
            int(binding_revision),
            source_digest,
            policy,
            files_tuple,
        )
        if hashlib.sha256(canonical_json(identity)).hexdigest() != metadata.get(
            "index_digest"
        ):
            return False, {}
        return True, files
    except (TypeError, ValueError, json.JSONDecodeError):
        return False, {}


def _binding_root(binding: SourceBinding, source_root: Path) -> Path:
    locator = Path(binding.locator.value)
    if (
        binding.locator.kind != "local-path"
        or not locator.is_absolute()
        or locator.is_symlink()
        or not locator.is_dir()
    ):
        raise SourceCodeIndexError("source code binding root is unsafe")
    resolved = locator.resolve()
    if resolved != source_root.resolve():
        raise SourceCodeIndexError("source code root does not match the binding")
    return resolved


def _index_identity(
    project_id: str,
    binding_id: str,
    binding_revision: int,
    source_digest: str,
    policy: SourceCodeIndexPolicy,
    files: tuple[IndexedCodeFile, ...],
) -> dict[str, object]:
    return {
        "index_revision": policy.index_revision,
        "project_id": project_id,
        "binding_id": binding_id,
        "binding_revision": binding_revision,
        "source_digest": source_digest,
        "policy_digest": policy.policy_digest,
        "embedding_profile_id": policy.offline_embedding_profile_id,
        "vector_dimensions": policy.vector_dimensions,
        "files": [
            {
                "relative_path": item.relative_path,
                "content_sha256": item.content_sha256,
                "size": item.size,
                "language": item.language,
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "start_offset": chunk.start_offset,
                        "end_offset": chunk.end_offset,
                        "content_sha256": chunk.content_sha256,
                        "symbols": list(chunk.symbols),
                        "vector_sha256": hashlib.sha256(
                            canonical_json(list(chunk.vector))
                        ).hexdigest(),
                    }
                    for chunk in item.chunks
                ],
            }
            for item in files
        ],
    }


def _validate_authorization(
    authorization: AdapterAuthorization,
    binding: SourceBinding,
    operation: str,
) -> None:
    request = authorization.request
    if (
        request.adapter_id != LOCAL_SOURCE_CODE_ADAPTER.adapter_id
        or request.operation != operation
        or request.binding_id != binding.binding_id
        or request.binding_revision != binding.revision
        or request.policy_effect == "deny"
        or request.mutation_effect
        or request.network_effect
        or binding.source_kind != "project"
        or binding.default_access != "read-only"
        or "write" in binding.capabilities
        or not {"read", "metadata"}.issubset(binding.capabilities)
    ):
        raise SourceCodeIndexError(
            "source code adapter authorization does not match the request"
        )


def prepare_source_code_index(
    repo_root: Path,
    data_root: Path,
    project_id: str,
    binding: SourceBinding,
    source_root: Path,
    discovery: DiscoveryResult,
    ownership: OwnershipResolver,
    authorization: AdapterAuthorization,
) -> SourceCodeIndexPlan:
    """Prepare a contentless index and reuse unchanged verified file chunks."""

    if not IDENTIFIER.fullmatch(project_id) or project_id != binding.source_id:
        raise SourceCodeIndexError("source code project identity is invalid")
    _validate_authorization(authorization, binding, "index")
    if (
        discovery.binding_id != binding.binding_id
        or discovery.source_id != binding.source_id
        or discovery.binding_revision != binding.revision
    ):
        raise SourceCodeIndexError("source discovery does not match the binding")
    root = _binding_root(binding, source_root)
    policy = load_source_code_index_policy(repo_root)
    target = source_code_index_path(data_root, project_id)
    _, existing = _load_existing_files(
        target,
        project_id=project_id,
        binding_id=binding.binding_id,
        policy=policy,
    )
    selected: list[tuple[FileEvidence, str]] = []
    skipped = {
        "unsupported": 0,
        "too_large": 0,
        "non_utf8_or_binary": 0,
    }
    for evidence in discovery.files:
        language = _language(evidence.relative_path, policy)
        if language is None:
            skipped["unsupported"] += 1
            continue
        if evidence.size > policy.maximum_indexed_file_bytes:
            skipped["too_large"] += 1
            continue
        selected.append((evidence, language))
    files: list[IndexedCodeFile] = []
    processed = 0
    reused = 0
    for evidence, language in selected:
        current = existing.get(evidence.relative_path)
        if (
            current is not None
            and current.content_sha256 == evidence.sha256
            and current.size == evidence.size
            and current.language == language
        ):
            files.append(current)
            reused += 1
            continue
        try:
            files.append(
                _build_file(project_id, root, evidence, language, policy)
            )
            processed += 1
        except SourceCodeIndexError as exc:
            if str(exc) in {
                "source file is not valid UTF-8",
                "source file contains binary content",
            }:
                skipped["non_utf8_or_binary"] += 1
                continue
            raise
    files_tuple = tuple(sorted(files, key=lambda item: item.relative_path))
    chunk_count = sum(len(item.chunks) for item in files_tuple)
    if chunk_count > policy.maximum_chunks:
        raise SourceCodeIndexError("source code index exceeds the chunk limit")
    current_paths = {item.relative_path for item in files_tuple}
    removed = len(set(existing) - current_paths)
    identity = _index_identity(
        project_id,
        binding.binding_id,
        binding.revision,
        discovery.root_digest,
        policy,
        files_tuple,
    )
    index_digest = hashlib.sha256(canonical_json(identity)).hexdigest()
    target_ref = f"{INDEX_DIRECTORY_REF}/{project_id}.sqlite"
    mutation = plan_mutation(
        ownership,
        operation="update" if target.exists() else "create",
        target_ref=target_ref,
        expected_ownership="derived",
        change_digest=index_digest,
        reversible=True,
    )
    return SourceCodeIndexPlan(
        project_id,
        binding.binding_id,
        binding.revision,
        root,
        discovery.root_digest,
        policy.policy_digest,
        policy.offline_embedding_profile_id,
        policy.vector_dimensions,
        files_tuple,
        processed,
        reused,
        removed,
        skipped,
        index_digest,
        mutation,
    )


def _create_index(path: Path, plan: SourceCodeIndexPlan) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE files (relative_path TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, size INTEGER NOT NULL, language TEXT NOT NULL, chunk_count INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, relative_path TEXT NOT NULL REFERENCES files(relative_path), start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, content_sha256 TEXT NOT NULL, language TEXT NOT NULL, symbols_json TEXT NOT NULL, vector_json TEXT NOT NULL)"
        )
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, relative_path, language, symbols, tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.Error as exc:
            raise SourceCodeIndexError("SQLite FTS5 support is required") from exc
        metadata = {
            "index_revision": "1",
            "project_id": plan.project_id,
            "binding_id": plan.binding_id,
            "binding_revision": str(plan.binding_revision),
            "source_digest": plan.source_digest,
            "policy_digest": plan.policy_digest,
            "index_digest": plan.index_digest,
            "embedding_profile_id": plan.embedding_profile_id,
            "vector_dimensions": str(plan.vector_dimensions),
            "file_count": str(len(plan.files)),
            "chunk_count": str(plan.chunk_count),
            "source_content_persisted": "false",
            "remote_provider_used": "false",
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            tuple(sorted(metadata.items())),
        )
        for indexed_file in plan.files:
            connection.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?)",
                (
                    indexed_file.relative_path,
                    indexed_file.content_sha256,
                    indexed_file.size,
                    indexed_file.language,
                    len(indexed_file.chunks),
                ),
            )
            for chunk in indexed_file.chunks:
                symbols_json = json.dumps(
                    list(chunk.symbols), ensure_ascii=False, separators=(",", ":")
                )
                vector_json = json.dumps(
                    list(chunk.vector), separators=(",", ":")
                )
                connection.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        chunk.relative_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.start_offset,
                        chunk.end_offset,
                        chunk.content_sha256,
                        chunk.language,
                        symbols_json,
                        vector_json,
                    ),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(chunk_id, relative_path, language, symbols) VALUES (?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        chunk.relative_path,
                        chunk.language,
                        " ".join(chunk.symbols),
                    ),
                )
        connection.commit()
    finally:
        connection.close()


def apply_source_code_index(
    data_root: Path,
    plan: SourceCodeIndexPlan,
    authorization: MutationAuthorization,
) -> dict[str, object]:
    """Install an exact contentless source-code index through atomic replacement."""

    if (
        authorization.plan.plan_id != plan.plan_id
        or not authorization.dry_run_verified
        or authorization.plan.ownership != "derived"
        or authorization.plan.change_digest != plan.index_digest
    ):
        raise SourceCodeIndexError(
            "source code index authorization does not match the plan"
        )
    for indexed_file in plan.files:
        evidence = FileEvidence(
            indexed_file.relative_path,
            "source",
            indexed_file.size,
            indexed_file.content_sha256,
        )
        source = _safe_source_file(plan.source_root, indexed_file.relative_path)
        before = source.stat(follow_symlinks=False)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        after = source.stat(follow_symlinks=False)
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or after.st_size != evidence.size
            or digest != evidence.sha256
        ):
            raise SourceCodeIndexError(
                "source code index plan is stale; reintegrate the project"
            )
    target = source_code_index_path(data_root, plan.project_id)
    expected_operation = "update" if target.exists() else "create"
    if plan.mutation.operation != expected_operation:
        raise SourceCodeIndexError("source code index target changed after planning")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise SourceCodeIndexError("source code index path may not use symbolic links")
    handle, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{plan.project_id}.",
        suffix=".sqlite",
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        _create_index(temporary, plan)
        verification = sqlite3.connect(temporary)
        try:
            metadata = _metadata(verification)
            file_count = verification.execute(
                "SELECT count(*) FROM files"
            ).fetchone()[0]
            chunk_count = verification.execute(
                "SELECT count(*) FROM chunks"
            ).fetchone()[0]
            fts_count = verification.execute(
                "SELECT count(*) FROM chunks_fts"
            ).fetchone()[0]
            integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            verification.close()
        if (
            metadata.get("index_digest") != plan.index_digest
            or metadata.get("source_content_persisted") != "false"
            or file_count != len(plan.files)
            or chunk_count != plan.chunk_count
            or fts_count != plan.chunk_count
            or integrity != "ok"
        ):
            raise SourceCodeIndexError("source code index verification failed")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "index_revision": 1,
        "project_id": plan.project_id,
        "source_digest": plan.source_digest,
        "index_digest": plan.index_digest,
        "embedding_profile_id": plan.embedding_profile_id,
        "vector_dimensions": plan.vector_dimensions,
        "file_count": len(plan.files),
        "chunk_count": plan.chunk_count,
        "processed_file_count": plan.processed_file_count,
        "reused_file_count": plan.reused_file_count,
        "removed_file_count": plan.removed_file_count,
        "database_bytes": target.stat().st_size,
        "integrity_verified": True,
        "source_copy": False,
        "source_content_persisted": False,
        "remote_provider_used": False,
    }


def source_code_index_summary(
    repo_root: Path,
    data_root: Path,
    project_id: str,
    *,
    binding_id: str | None = None,
    source_digest: str | None = None,
) -> dict[str, object]:
    """Inspect one source-code index without disclosing its physical path."""

    policy = load_source_code_index_policy(repo_root)
    target = source_code_index_path(data_root, project_id)
    unavailable = {
        "status": "unavailable",
        "project_id": project_id,
        "file_count": 0,
        "chunk_count": 0,
        "embedding_profile_id": policy.offline_embedding_profile_id,
        "vector_dimensions": policy.vector_dimensions,
        "source_content_persisted": False,
        "paths_disclosed": False,
    }
    if not target.is_file() or target.is_symlink():
        return unavailable
    try:
        connection = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            metadata = _metadata(connection)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            files = connection.execute("SELECT count(*) FROM files").fetchone()[0]
            chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        finally:
            connection.close()
    except (OSError, sqlite3.Error, SourceCodeIndexError):
        return {**unavailable, "status": "invalid"}
    content_valid, indexed_files = _load_existing_files(
        target,
        project_id=project_id,
        binding_id=metadata.get("binding_id", ""),
        policy=policy,
    )
    current = bool(
        integrity == "ok"
        and content_valid
        and len(indexed_files) == files
        and metadata.get("index_revision") == str(policy.index_revision)
        and metadata.get("project_id") == project_id
        and metadata.get("policy_digest") == policy.policy_digest
        and metadata.get("embedding_profile_id")
        == policy.offline_embedding_profile_id
        and metadata.get("vector_dimensions") == str(policy.vector_dimensions)
        and metadata.get("source_content_persisted") == "false"
        and metadata.get("remote_provider_used") == "false"
        and metadata.get("file_count") == str(files)
        and metadata.get("chunk_count") == str(chunks)
        and (binding_id is None or metadata.get("binding_id") == binding_id)
        and (source_digest is None or metadata.get("source_digest") == source_digest)
    )
    try:
        vector_dimensions = int(metadata.get("vector_dimensions", "0"))
    except ValueError:
        vector_dimensions = 0
        current = False
    return {
        "status": "current" if current else "stale",
        "project_id": project_id,
        "source_digest": metadata.get("source_digest"),
        "index_digest": metadata.get("index_digest"),
        "file_count": int(files),
        "chunk_count": int(chunks),
        "embedding_profile_id": metadata.get("embedding_profile_id"),
        "vector_dimensions": vector_dimensions,
        "database_bytes": target.stat().st_size,
        "integrity_verified": integrity == "ok",
        "source_content_persisted": False,
        "paths_disclosed": False,
    }


def source_code_index_is_current(
    repo_root: Path,
    data_root: Path,
    project_id: str,
    binding_id: str,
    source_digest: str,
) -> bool:
    return (
        source_code_index_summary(
            repo_root,
            data_root,
            project_id,
            binding_id=binding_id,
            source_digest=source_digest,
        )["status"]
        == "current"
    )


def parse_source_code_query(payload: object) -> SourceCodeQuery:
    expected = {
        "schema_ref",
        "schema_version",
        "query_id",
        "project_id",
        "text",
        "languages",
        "path_prefix",
        "include_content",
        "limit",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise SourceCodeIndexError("source code query fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/source-code-query.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise SourceCodeIndexError("source code query schema is invalid")
    query_id = payload.get("query_id")
    project_id = payload.get("project_id")
    text = payload.get("text")
    languages = payload.get("languages")
    prefix = payload.get("path_prefix")
    include_content = payload.get("include_content")
    limit = payload.get("limit")
    if (
        not isinstance(query_id, str)
        or not IDENTIFIER.fullmatch(query_id)
        or not isinstance(project_id, str)
        or not IDENTIFIER.fullmatch(project_id)
        or not isinstance(text, str)
        or not text.strip()
        or len(text) > MAX_QUERY_LENGTH
        or not isinstance(languages, list)
        or any(
            not isinstance(item, str) or not IDENTIFIER.fullmatch(item)
            for item in languages
        )
        or len(set(languages)) != len(languages)
        or not isinstance(include_content, bool)
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RESULT_LIMIT
    ):
        raise SourceCodeIndexError("source code query values are invalid")
    normalized_prefix = None
    if prefix is not None:
        if not isinstance(prefix, str) or not prefix.strip() or "\\" in prefix:
            raise SourceCodeIndexError("source code path prefix is invalid")
        candidate = PurePosixPath(prefix.strip().strip("/"))
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SourceCodeIndexError("source code path prefix is unsafe")
        normalized_prefix = candidate.as_posix()
    return SourceCodeQuery(
        query_id,
        project_id,
        unicodedata.normalize("NFC", text.strip()),
        tuple(languages),
        normalized_prefix,
        include_content,
        limit,
    )


def _fts_scores(connection: sqlite3.Connection, text: str) -> dict[str, float]:
    tokens = tuple(dict.fromkeys(_normalized_tokens(text)))[:32]
    if not tokens:
        return {}
    expression = " OR ".join(
        '"' + token.replace('"', '""') + '"' for token in tokens
    )
    try:
        rows = connection.execute(
            "SELECT chunk_id, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ?",
            (expression,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise SourceCodeIndexError("source code FTS query failed") from exc
    raw = {str(chunk_id): max(0.0, -float(rank)) for chunk_id, rank in rows}
    maximum = max(raw.values(), default=0.0)
    if maximum == 0:
        return {chunk_id: 1.0 for chunk_id in raw}
    return {chunk_id: value / maximum for chunk_id, value in raw.items()}


def _exact_score(query: str, relative_path: str, symbols: tuple[str, ...]) -> float:
    needle = unicodedata.normalize("NFKC", query).casefold()
    normalized_symbols = tuple(item.casefold() for item in symbols)
    path = relative_path.casefold()
    if needle in normalized_symbols:
        return 1.0
    if needle in path:
        return 0.85
    tokens = set(_normalized_tokens(query))
    metadata_tokens = set(_normalized_tokens(" ".join((relative_path, *symbols))))
    if not tokens:
        return 0.0
    overlap = len(tokens.intersection(metadata_tokens)) / len(tokens)
    return min(0.7, overlap)


def retrieve_source_code(
    repo_root: Path,
    data_root: Path,
    binding: SourceBinding,
    source_root: Path,
    expected_source_digest: str,
    query: SourceCodeQuery,
    authorization: AdapterAuthorization,
) -> dict[str, object]:
    """Search vectors, then optionally read verified source chunks in place."""

    query = parse_source_code_query(query.as_dict())
    if query.project_id != binding.source_id:
        raise SourceCodeIndexError("source code query project does not match binding")
    _validate_authorization(authorization, binding, "retrieve")
    source_root = _binding_root(binding, source_root)
    policy = load_source_code_index_policy(repo_root)
    target = source_code_index_path(data_root, query.project_id)
    if not target.is_file() or target.is_symlink():
        raise SourceCodeIndexError(
            "source code index is unavailable; integrate the project first"
        )
    content_valid, _ = _load_existing_files(
        target,
        project_id=query.project_id,
        binding_id=binding.binding_id,
        policy=policy,
    )
    if not content_valid:
        raise SourceCodeIndexError(
            "source code index is invalid; reintegrate the project"
        )
    connection = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        metadata = _metadata(connection)
        if (
            metadata.get("index_revision") != str(policy.index_revision)
            or metadata.get("project_id") != query.project_id
            or metadata.get("binding_id") != binding.binding_id
            or metadata.get("binding_revision") != str(binding.revision)
            or metadata.get("source_digest") != expected_source_digest
            or metadata.get("policy_digest") != policy.policy_digest
            or metadata.get("embedding_profile_id")
            != policy.offline_embedding_profile_id
            or metadata.get("source_content_persisted") != "false"
        ):
            raise SourceCodeIndexError(
                "source code index is stale; reintegrate the project"
            )
        fts_scores = _fts_scores(connection, query.text)
        rows = connection.execute(
            "SELECT c.chunk_id, c.relative_path, c.start_line, c.end_line, c.start_offset, c.end_offset, c.content_sha256, c.language, c.symbols_json, c.vector_json, f.content_sha256, f.size FROM chunks c JOIN files f ON f.relative_path = c.relative_path"
        ).fetchall()
    finally:
        connection.close()
    query_vector = _vector(query.text, policy.vector_dimensions)
    candidates = []
    for row in rows:
        language = str(row[7])
        relative_path = str(row[1])
        if query.languages and language not in query.languages:
            continue
        if query.path_prefix is not None and not (
            relative_path == query.path_prefix
            or relative_path.startswith(query.path_prefix + "/")
        ):
            continue
        try:
            symbols_payload = json.loads(row[8])
            vector_payload = json.loads(row[9])
        except json.JSONDecodeError as exc:
            raise SourceCodeIndexError("source code index row is invalid") from exc
        if (
            not isinstance(symbols_payload, list)
            or not isinstance(vector_payload, list)
            or len(vector_payload) != policy.vector_dimensions
        ):
            raise SourceCodeIndexError("source code index row shape is invalid")
        symbols = tuple(str(item) for item in symbols_payload)
        vector = tuple(float(item) for item in vector_payload)
        exact = _exact_score(query.text, relative_path, symbols)
        fts = fts_scores.get(str(row[0]), 0.0)
        vector_score = _cosine(query_vector, vector)
        breakdown = {
            "exact": float(f"{exact:.6f}"),
            "fts": float(f"{fts:.6f}"),
            "vector": float(f"{vector_score:.6f}"),
        }
        score = sum(WEIGHTS[key] * breakdown[key] for key in WEIGHTS)
        candidates.append(
            {
                "chunk_id": str(row[0]),
                "relative_path": relative_path,
                "start_line": int(row[2]),
                "end_line": int(row[3]),
                "start_offset": int(row[4]),
                "end_offset": int(row[5]),
                "content_sha256": str(row[6]),
                "language": language,
                "symbols": list(symbols),
                "score": float(f"{score:.6f}"),
                "score_breakdown": breakdown,
                "file_sha256": str(row[10]),
                "file_size": int(row[11]),
            }
        )
    candidates.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item["relative_path"]),
            int(item["start_offset"]),
        )
    )
    hits = candidates[: query.limit]
    content_budget = policy.maximum_search_content_characters
    text_cache: dict[str, str] = {}
    for hit in hits:
        hit["source_ref"] = f"project:{query.project_id}"
        hit["content"] = None
        hit["content_truncated"] = False
        if query.include_content:
            relative_path = str(hit["relative_path"])
            if relative_path not in text_cache:
                evidence = FileEvidence(
                    relative_path,
                    "source",
                    int(hit["file_size"]),
                    str(hit["file_sha256"]),
                )
                text_cache[relative_path] = _read_verified_text(
                    source_root.resolve(), evidence
                )
            chunk_text = text_cache[relative_path][
                int(hit["start_offset"]) : int(hit["end_offset"])
            ]
            if hashlib.sha256(chunk_text.encode("utf-8")).hexdigest() != hit[
                "content_sha256"
            ]:
                raise SourceCodeIndexError(
                    "source code chunk changed after indexing; reintegrate the project"
                )
            included = chunk_text[:content_budget]
            hit["content"] = included
            hit["content_truncated"] = len(included) < len(chunk_text)
            content_budget -= len(included)
        hit.pop("file_sha256")
        hit.pop("file_size")
        hit.pop("start_offset")
        hit.pop("end_offset")
    return {
        "schema_ref": "schemas/source-code-result.schema.json",
        "schema_version": 1,
        "query_id": query.query_id,
        "project_id": query.project_id,
        "query_digest": query.query_digest,
        "index_digest": metadata["index_digest"],
        "source_digest": metadata["source_digest"],
        "embedding_profile_id": metadata["embedding_profile_id"],
        "vector_dimensions": policy.vector_dimensions,
        "weights": dict(WEIGHTS),
        "candidate_count": len(candidates),
        "hit_count": len(hits),
        "hits": hits,
        "source_content_persisted": False,
        "source_read_in_place": query.include_content,
        "paths_disclosed": False,
        "remote": False,
    }

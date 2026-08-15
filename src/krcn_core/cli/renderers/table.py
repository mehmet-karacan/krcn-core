"""Small deterministic table and display helpers for human CLI output."""

from __future__ import annotations

from typing import Mapping


def text_table(headers: list[str], rows: list[list[object]]) -> str:
    values = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in values:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    lines = [
        " | ".join(
            header.ljust(widths[index]) for index, header in enumerate(headers)
        ),
        "-+-".join("-" * width for width in widths),
    ]
    lines.extend(
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in values
    )
    return "\n".join(lines)


def display_status(value: object) -> str:
    translations = {
        "active": "aktif",
        "archived": "arşiv",
        "complete": "tamam",
        "incomplete": "eksik",
        "invalid": "geçersiz",
        "not-integrated": "entegre değil",
        "stale": "güncel değil",
        "planned": "planlandı",
        "blocked": "engelli",
        "request": "talep",
        "defect": "defect",
        "task": "görev",
        "subtask": "alt görev",
        "decision": "karar",
    }
    text = str(value or "-")
    return translations.get(text, text)


def display_timestamp(value: object) -> str:
    text = str(value or "")
    if len(text) >= 16 and "T" in text:
        return text[:16].replace("T", " ")
    return text or "-"


def shorten(value: object, limit: int) -> str:
    text = str(value or "-")
    if len(text) <= limit:
        return text
    suffix_length = min(12, limit // 3)
    prefix_length = limit - suffix_length - 3
    return text[:prefix_length] + "..." + text[-suffix_length:]


def work_count_pair(project: Mapping[str, object], group: str) -> str:
    work_counts = project.get("work_counts")
    if not isinstance(work_counts, dict):
        return "0/0"
    counts = work_counts.get(group)
    if not isinstance(counts, dict):
        return "0/0"
    return f"{counts.get('active', 0)}/{counts.get('historical', 0)}"

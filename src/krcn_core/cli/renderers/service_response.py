"""Explicit operation registry for human CLI response rendering."""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Callable, Mapping

from krcn_core.application_contract import ServiceResponse


HUMAN_RENDERER_KEYS: Mapping[str, str] = MappingProxyType(
    {
        "project.list": "project_menu",
        "project.resume": "project_resume",
        "work.list": "work_list",
        "work.documents.migrate-layout": "work_document_migration",
        "work.documents.process": "work_document_processing",
        "work.index-readable": "work_index",
        "research.action": "research_action",
    }
)


def render_service_response(
    response: ServiceResponse,
    output_format: str | None,
    renderers: Mapping[str, Callable[..., str]],
) -> tuple[str, int]:
    """Render one response without discovering handlers dynamically."""

    payload = response.as_dict()
    if output_format == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        renderer_key = HUMAN_RENDERER_KEYS.get(response.operation)
        renderer = renderers.get(renderer_key) if renderer_key is not None else None
        if renderer_key is None:
            text = (
                f"{response.status}\t{response.operation}\n"
                + json.dumps(response.data, ensure_ascii=False, indent=2)
            )
        elif not callable(renderer):
            raise ValueError(f"CLI renderer is unavailable: {renderer_key}")
        elif renderer_key in {
            "work_document_migration",
            "work_document_processing",
            "work_index",
            "research_action",
        }:
            text = renderer(response.status, response.data)
        else:
            text = renderer(response.data)
    exit_code = 3 if response.status in {"blocked", "unavailable"} else 0
    return text, exit_code

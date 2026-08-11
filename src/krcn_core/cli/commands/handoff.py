"""Handoff command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("handoff", ("handoff",), "public", "mixed", "redesign"),
    )

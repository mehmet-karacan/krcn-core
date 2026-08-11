"""Skill command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("skill-list", ("skill", "list"), "public", "read", "preserve"),
        CommandSpec("skill-show", ("skill", "show"), "public", "read", "preserve"),
    )

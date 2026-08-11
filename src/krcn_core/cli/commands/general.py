"""General command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("root", ("root",), "public", "read", "redesign"),
        CommandSpec("validate", ("validate",), "public", "read", "redesign"),
        CommandSpec("combined-search", ("ara",), "public", "read", "redesign"),
    )

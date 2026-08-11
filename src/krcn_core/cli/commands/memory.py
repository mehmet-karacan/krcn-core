"""Memory command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("memory-index", ("memory", "index"), "public", "write", "redesign"),
        CommandSpec("memory-semantic-search", ("memory", "semantik-ara"), "public", "read", "redesign"),
    )

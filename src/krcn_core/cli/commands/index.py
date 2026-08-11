"""Index command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("index-build", ("index", "build"), "public", "write", "redesign"),
        CommandSpec("index-update", ("index", "update"), "public", "write", "redesign"),
        CommandSpec("index-worker", ("index", "_worker"), "internal", "write", "internal-only"),
        CommandSpec("index-status", ("index", "status"), "public", "read", "preserve"),
        CommandSpec("index-query", ("index", "query"), "public", "read", "preserve"),
        CommandSpec("index-semantic-search", ("index", "semantik-ara"), "public", "read", "redesign"),
    )

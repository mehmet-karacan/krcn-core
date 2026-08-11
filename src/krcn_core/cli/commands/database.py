"""Database index command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("database-connection-add", ("db-index", "baglanti-ekle"), "public", "write", "redesign"),
        CommandSpec("database-index-build", ("db-index", "build"), "public", "write", "defer"),
        CommandSpec("database-index-status", ("db-index", "status"), "public", "read", "redesign"),
        CommandSpec("database-semantic-search", ("db-index", "semantik-ara"), "public", "read", "redesign"),
    )

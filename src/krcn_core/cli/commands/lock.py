"""Lock command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("lock-acquire", ("lock", "acquire"), "public", "write", "redesign"),
        CommandSpec("lock-release", ("lock", "release"), "public", "write", "redesign"),
        CommandSpec("lock-check", ("lock", "check"), "public", "read", "preserve"),
        CommandSpec("lock-list", ("lock", "list"), "public", "read", "preserve"),
        CommandSpec("lock-force-release", ("lock", "force-release"), "public", "write", "redesign"),
    )

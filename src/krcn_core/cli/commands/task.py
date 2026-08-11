"""Task command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("task-list", ("task", "list"), "public", "read", "preserve"),
        CommandSpec("task-checkpoint", ("task", "checkpoint"), "public", "write", "redesign"),
        CommandSpec("task-resume-summary", ("task", "nerede-kaldik"), "public", "read", "preserve"),
    )

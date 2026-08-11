"""Project command metadata."""

from ..models import CommandSpec


def specs() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("project-list", ("project", "list"), "public", "read", "redesign"),
        CommandSpec("project-onboard", ("project", "onboard"), "public", "write", "redesign"),
        CommandSpec("project-rescan", ("project", "rescan"), "public", "write", "redesign"),
    )

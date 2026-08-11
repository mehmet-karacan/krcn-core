"""Command registry assembled from small command families."""

from __future__ import annotations

from collections.abc import Iterable

from .commands import database, general, handoff, index, lock, memory, project, skill, task
from .models import CommandSpec


class CommandRegistry:
    """Store immutable command metadata with duplicate protection."""

    def __init__(self, commands: Iterable[CommandSpec]) -> None:
        by_id: dict[str, CommandSpec] = {}
        by_path: dict[tuple[str, ...], CommandSpec] = {}
        for command in commands:
            if command.command_id in by_id:
                raise ValueError(f"duplicate command id: {command.command_id}")
            if command.path in by_path:
                raise ValueError(f"duplicate command path: {command.command}")
            by_id[command.command_id] = command
            by_path[command.path] = command
        self._by_id = by_id
        self._by_path = by_path

    def all(self, *, include_internal: bool = True) -> tuple[CommandSpec, ...]:
        commands = self._by_id.values()
        if not include_internal:
            commands = (item for item in commands if item.visibility == "public")
        return tuple(sorted(commands, key=lambda item: item.path))

    def by_id(self, command_id: str) -> CommandSpec:
        return self._by_id[command_id]

    def by_path(self, *path: str) -> CommandSpec:
        return self._by_path[tuple(path)]


def compatibility_registry() -> CommandRegistry:
    """Build the reviewed legacy command catalog from modular families."""

    families = (
        general.specs(),
        project.specs(),
        task.specs(),
        index.specs(),
        memory.specs(),
        database.specs(),
        lock.specs(),
        handoff.specs(),
        skill.specs(),
    )
    return CommandRegistry(command for family in families for command in family)

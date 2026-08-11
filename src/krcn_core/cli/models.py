"""Portable command metadata used by CLI adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CommandVisibility = Literal["public", "internal"]
CommandBehavior = Literal["read", "write", "mixed"]
CommandDisposition = Literal["preserve", "redesign", "defer", "internal-only"]


@dataclass(frozen=True)
class CommandSpec:
    """Describe a legacy command without importing its implementation."""

    command_id: str
    path: tuple[str, ...]
    visibility: CommandVisibility
    behavior: CommandBehavior
    disposition: CommandDisposition

    def __post_init__(self) -> None:
        if not self.command_id or not self.path or any(not part for part in self.path):
            raise ValueError("command id and path parts must be non-empty")

    @property
    def command(self) -> str:
        return " ".join(self.path)

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.command_id,
            "command": self.command,
            "visibility": self.visibility,
            "behavior": self.behavior,
            "disposition": self.disposition,
        }

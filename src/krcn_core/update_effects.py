"""Trusted migration and derived-action descriptors for merge planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
OWNERSHIP_CLASSES = {
    "core",
    "runtime",
    "user-data",
    "derived",
    "secrets",
    "unmanaged",
}


class UpdateEffectError(ValueError):
    """Raised when a trusted update effect descriptor is invalid."""


@dataclass(frozen=True)
class MigrationSpec:
    migration_id: str
    schema_name: str
    from_version: int
    to_version: int
    ownership: str
    target_ref: str
    reversible: bool = True

    def __post_init__(self) -> None:
        if not IDENTIFIER.fullmatch(self.migration_id):
            raise UpdateEffectError("migration id must be portable")
        if not IDENTIFIER.fullmatch(self.schema_name):
            raise UpdateEffectError("migration schema name must be portable")
        if (
            not isinstance(self.from_version, int)
            or isinstance(self.from_version, bool)
            or self.from_version < 1
            or not isinstance(self.to_version, int)
            or isinstance(self.to_version, bool)
            or self.to_version <= self.from_version
        ):
            raise UpdateEffectError("migration version transition is invalid")
        if self.ownership not in OWNERSHIP_CLASSES:
            raise UpdateEffectError("migration ownership is invalid")
        if self.ownership not in {"runtime", "user-data", "derived"}:
            raise UpdateEffectError("migration may not target this ownership class")
        if (
            not isinstance(self.target_ref, str)
            or not self.target_ref.startswith(".krcn/")
            or "\\" in self.target_ref
            or ".." in self.target_ref.split("/")
            or self.target_ref.endswith("/")
        ):
            raise UpdateEffectError("migration target must be portable local data")
        if not self.reversible:
            raise UpdateEffectError("irreversible migration is prohibited")

    @property
    def approval_required(self) -> bool:
        return self.ownership in {"user-data", "secrets", "unmanaged"}

    def as_dict(self) -> dict[str, object]:
        return {
            "migration_id": self.migration_id,
            "schema_name": self.schema_name,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "ownership": self.ownership,
            "target_ref": self.target_ref,
            "reversible": self.reversible,
            "approval_required": self.approval_required,
        }


@dataclass(frozen=True)
class DerivedActionSpec:
    action_id: str
    target_ref: str
    action: str
    approval_required: bool = False

    def __post_init__(self) -> None:
        if not IDENTIFIER.fullmatch(self.action_id):
            raise UpdateEffectError("derived action id must be portable")
        if (
            not isinstance(self.target_ref, str)
            or not self.target_ref.startswith(".krcn/derived/")
            or "\\" in self.target_ref
            or ".." in self.target_ref.split("/")
            or self.target_ref.endswith("/")
        ):
            raise UpdateEffectError("derived action target must stay in derived data")
        if self.action not in {"rebuild", "validate"}:
            raise UpdateEffectError("derived action is invalid")
        if not isinstance(self.approval_required, bool):
            raise UpdateEffectError("derived action approval flag must be boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "target_ref": self.target_ref,
            "action": self.action,
            "ownership": "derived",
            "approval_required": self.approval_required,
        }


class MigrationRegistry:
    def __init__(self, specs: Iterable[MigrationSpec] = ()) -> None:
        self._specs: dict[str, MigrationSpec] = {}
        for spec in specs:
            if spec.migration_id in self._specs:
                raise UpdateEffectError("duplicate migration id")
            self._specs[spec.migration_id] = spec

    def resolve(self, migration_ids: tuple[str, ...]) -> tuple[MigrationSpec, ...]:
        missing = set(migration_ids) - set(self._specs)
        if missing:
            raise UpdateEffectError(
                "unregistered migrations: " + ", ".join(sorted(missing))
            )
        return tuple(self._specs[item] for item in migration_ids)


class DerivedActionRegistry:
    def __init__(self, specs: Iterable[DerivedActionSpec] = ()) -> None:
        self._specs: dict[str, DerivedActionSpec] = {}
        for spec in specs:
            if spec.action_id in self._specs:
                raise UpdateEffectError("duplicate derived action id")
            self._specs[spec.action_id] = spec

    def resolve(
        self,
        action_ids: tuple[str, ...],
    ) -> tuple[DerivedActionSpec, ...]:
        missing = set(action_ids) - set(self._specs)
        if missing:
            raise UpdateEffectError(
                "unregistered derived actions: " + ", ".join(sorted(missing))
            )
        return tuple(self._specs[item] for item in action_ids)

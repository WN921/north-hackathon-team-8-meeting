"""Composite room domain model.

RFC-0001: Meeting room domain model and rule engine.
Composite rooms are logical booking targets that lock all member rooms for the same time window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class CompositeRoom:
    """A logical room composed of multiple physical rooms.

    RFC-0001: A composite booking must be equivalent to booking every member
    room at the same time, so member rooms cannot be booked separately during
    that window.
    """

    id: str
    name: str
    member_room_ids: list[str]
    capacity: int
    equipment: list[str] = field(default_factory=list)
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def has_equipment(self, equipment: list[str]) -> bool:
        """Return True when all requested equipment is available in the composite."""

        current = {item.lower() for item in self.equipment}
        return all(item.lower() in current for item in equipment)

    def update_from(
        self,
        *,
        name: str | None = None,
        member_room_ids: list[str] | None = None,
        capacity: int | None = None,
        equipment: list[str] | None = None,
        active: bool | None = None,
        updated_at: datetime,
    ) -> None:
        """Apply a partial composite-room update in place."""

        if name is not None:
            self.name = name
        if member_room_ids is not None:
            self.member_room_ids = list(member_room_ids)
        if capacity is not None:
            self.capacity = capacity
        if equipment is not None:
            self.equipment = list(equipment)
        if active is not None:
            self.active = active
        self.updated_at = updated_at

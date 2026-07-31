"""Room domain model.

RFC-0001: Meeting room domain model and rule engine.
Rooms are physical spaces that can be queried, booked, and displayed on the floor plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .common import OpeningSchedule


@dataclass(slots=True)
class Room:
    """A physical meeting room.

    RFC-0001: Room fields match the fixed-space model used by the rule engine,
    calendar, and floor-plan state.
    """

    id: str
    name: str
    type: str
    capacity: int
    location: str
    equipment: list[str] = field(default_factory=list)
    position: dict[str, float] | None = None
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def has_equipment(self, equipment: list[str]) -> bool:
        """Return True when all requested equipment is available."""

        current = {item.lower() for item in self.equipment}
        return all(item.lower() in current for item in equipment)

    def update_from(
        self,
        *,
        name: str | None = None,
        room_type: str | None = None,
        capacity: int | None = None,
        location: str | None = None,
        equipment: list[str] | None = None,
        position: dict[str, float] | None = None,
        active: bool | None = None,
        updated_at: datetime,
    ) -> None:
        """Apply a partial room update in place."""

        if name is not None:
            self.name = name
        if room_type is not None:
            self.type = room_type
        if capacity is not None:
            self.capacity = capacity
        if location is not None:
            self.location = location
        if equipment is not None:
            self.equipment = list(equipment)
        if position is not None:
            self.position = dict(position)
        if active is not None:
            self.active = active
        self.updated_at = updated_at


@dataclass(frozen=True, slots=True)
class RoomDetail:
    """Room detail returned by the domain service."""

    room: Room
    opening_schedules: list[OpeningSchedule]
    fixed_rule_summary: list[dict[str, Any]]

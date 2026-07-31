"""Domain models for rooms, rules, bookings and state revision. RFC-0001/RFC-0002."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

TargetType = Literal["room", "composite"]


@dataclass(slots=True)
class Position:
    """Room position on the local floor-plan SVG coordinate system."""

    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(slots=True)
class Room:
    """Meeting room domain object used by RFC-0001 and exposed by RFC-0002."""

    id: str
    name: str
    type: str
    location: str
    capacity: int
    equipment: list[str] = field(default_factory=list)
    position: Position | None = None
    protected: bool = False
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "location": self.location,
            "capacity": self.capacity,
            "equipment": list(self.equipment),
            "position": self.position.to_dict() if self.position else None,
            "protected": self.protected,
            "active": self.active,
        }


@dataclass(slots=True)
class CompositeRoom:
    """Composite space made of member rooms."""

    id: str
    name: str
    member_room_ids: list[str]
    capacity: int
    equipment: list[str] = field(default_factory=list)
    position: Position | None = None
    protected: bool = True
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "member_room_ids": list(self.member_room_ids),
            "capacity": self.capacity,
            "equipment": list(self.equipment),
            "position": self.position.to_dict() if self.position else None,
            "protected": self.protected,
            "active": self.active,
        }


@dataclass(slots=True)
class TimeWindow:
    """Rule time window. Recurrence may be null, weekly or weekly:tuesday."""

    start_at: str
    end_at: str
    recurrence: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"start_at": self.start_at, "end_at": self.end_at, "recurrence": self.recurrence}


@dataclass(slots=True)
class Rule:
    """Unavailability rule that blocks booking availability."""

    id: str
    rule_type: str
    target_type: TargetType
    target_id: str
    time_windows: list[TimeWindow]
    reason: str
    fixed: bool = False
    editable: bool = True
    match_key: str | None = None
    created_by: str | None = None
    updated_by: str | None = None

    def reason_code(self) -> str:
        if self.rule_type == "weekly_unavailable":
            return "WEEKLY_UNAVAILABLE"
        if self.rule_type == "temporary_maintenance":
            return "TEMPORARY_MAINTENANCE"
        if self.rule_type == "fixed_unavailable":
            return "FIXED_UNAVAILABLE"
        if self.fixed:
            return "FIXED_UNAVAILABLE"
        return "TEMPORARY_MAINTENANCE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.id,
            "rule_type": self.rule_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "time_windows": [window.to_dict() for window in self.time_windows],
            "reason": self.reason,
            "fixed": self.fixed,
            "editable": self.editable,
            "match_key": self.match_key,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
        }


@dataclass(slots=True)
class Booking:
    """Confirmed booking domain object."""

    id: str
    target_type: TargetType
    target_id: str
    start_at: str
    end_at: str
    title: str
    organizer_id: str
    attendees: list[str] = field(default_factory=list)
    description: str = ""
    status: str = "confirmed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "booking_id": self.id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "start_at": self.start_at,
            "end_at": self.end_at,
            "title": self.title,
            "organizer_id": self.organizer_id,
            "attendees": list(self.attendees),
            "description": self.description,
            "status": self.status,
        }

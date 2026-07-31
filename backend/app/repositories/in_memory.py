"""In-memory repository interfaces and implementations for the domain layer.

RFC-0001: Meeting room domain model and rule engine.
The API layer can later replace these with SQLite-backed repositories without
changing the rule engine or service semantics.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.domain.booking import Booking
from app.domain.common import AuditEvent, AvailabilityRequest, AvailabilityResult, TargetType
from app.domain.composite_room import CompositeRoom
from app.domain.room import Room
from app.domain.rule import RoomRule
from app.domain.rule_engine import MeetingRuleEngine
from app.domain.state_revision import StateRevisionStore


class RoomRepository(Protocol):
    def get(self, room_id: str) -> Room | None: ...
    def list(self) -> list[Room]: ...
    def save(self, room: Room) -> Room: ...
    def delete(self, room_id: str) -> None: ...


class CompositeRoomRepository(Protocol):
    def get(self, composite_id: str) -> CompositeRoom | None: ...
    def list(self) -> list[CompositeRoom]: ...
    def save(self, composite_room: CompositeRoom) -> CompositeRoom: ...
    def delete(self, composite_id: str) -> None: ...


class OpeningScheduleRepository(Protocol):
    def list_for_room(self, room_id: str) -> list[object]: ...
    def save(self, schedule: object) -> object: ...
    def clear_for_room(self, room_id: str) -> None: ...


@dataclass
class InMemoryOpeningScheduleRepository(OpeningScheduleRepository):
    schedules: dict[str, list[object]] = field(default_factory=dict)

    def list_for_room(self, room_id: str) -> list[object]:
        return list(self.schedules.get(room_id, []))

    def save(self, schedule: object) -> object:
        room_id = getattr(schedule, "room_id")
        self.schedules.setdefault(room_id, []).append(schedule)
        return schedule

    def clear_for_room(self, room_id: str) -> None:
        self.schedules.pop(room_id, None)


class RuleRepository(Protocol):
    def get(self, rule_id: str) -> RoomRule | None: ...
    def list_for_target(
        self,
        target_type: TargetType,
        target_id: str,
        *,
        include_protected: bool = True,
    ) -> list[RoomRule]: ...
    def list_all(self, *, include_protected: bool = True) -> list[RoomRule]: ...
    def save(self, rule: RoomRule) -> RoomRule: ...
    def delete(self, rule_id: str) -> None: ...


class BookingRepository(Protocol):
    def get(self, booking_id: str) -> Booking | None: ...
    def list_active(self) -> list[Booking]: ...
    def list_for_target(self, target_type: TargetType, target_id: str) -> list[Booking]: ...
    def save(self, booking: Booking) -> Booking: ...
    def delete(self, booking_id: str) -> None: ...


class BookingWindowRepository(Protocol):
    def list_for_booking(self, booking_id: str) -> list[object]: ...
    def save(self, booking_id: str, window: object) -> object: ...
    def clear(self, booking_id: str) -> None: ...


class AuditRepository(Protocol):
    def save(self, event: AuditEvent) -> AuditEvent: ...
    def list(self) -> list[AuditEvent]: ...


@dataclass
class InMemoryRoomRepository(RoomRepository):
    rooms: dict[str, Room] = field(default_factory=dict)

    def get(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    def list(self) -> list[Room]:
        return list(self.rooms.values())

    def save(self, room: Room) -> Room:
        self.rooms[room.id] = room
        return room

    def delete(self, room_id: str) -> None:
        self.rooms.pop(room_id, None)


@dataclass
class InMemoryCompositeRoomRepository(CompositeRoomRepository):
    composites: dict[str, CompositeRoom] = field(default_factory=dict)

    def get(self, composite_id: str) -> CompositeRoom | None:
        return self.composites.get(composite_id)

    def list(self) -> list[CompositeRoom]:
        return list(self.composites.values())

    def save(self, composite_room: CompositeRoom) -> CompositeRoom:
        self.composites[composite_room.id] = composite_room
        return composite_room

    def delete(self, composite_id: str) -> None:
        self.composites.pop(composite_id, None)


@dataclass
class InMemoryRuleRepository(RuleRepository):
    rules: dict[str, RoomRule] = field(default_factory=dict)

    def get(self, rule_id: str) -> RoomRule | None:
        return self.rules.get(rule_id)

    def list_for_target(
        self,
        target_type: TargetType,
        target_id: str,
        *,
        include_protected: bool = True,
    ) -> list[RoomRule]:
        return [
            rule
            for rule in self.rules.values()
            if rule.target_type == target_type and rule.target_id == target_id and (include_protected or not rule.protected)
        ]

    def list_all(self, *, include_protected: bool = True) -> list[RoomRule]:
        return [rule for rule in self.rules.values() if include_protected or not rule.protected]

    def save(self, rule: RoomRule) -> RoomRule:
        self.rules[rule.id] = rule
        return rule

    def delete(self, rule_id: str) -> None:
        self.rules.pop(rule_id, None)


@dataclass
class InMemoryBookingRepository(BookingRepository):
    bookings: dict[str, Booking] = field(default_factory=dict)

    def get(self, booking_id: str) -> Booking | None:
        return self.bookings.get(booking_id)

    def list_active(self) -> list[Booking]:
        return [booking for booking in self.bookings.values() if booking.is_active]

    def list(self) -> list[Booking]:
        return list(self.bookings.values())

    def list_for_target(self, target_type: TargetType, target_id: str) -> list[Booking]:
        return [
            booking
            for booking in self.bookings.values()
            if booking.is_active and booking.target_type == target_type and booking.target_id == target_id
        ]

    def save(self, booking: Booking) -> Booking:
        self.bookings[booking.id] = booking
        return booking

    def delete(self, booking_id: str) -> None:
        self.bookings.pop(booking_id, None)


@dataclass
class InMemoryAuditRepository(AuditRepository):
    events: list[AuditEvent] = field(default_factory=list)

    def save(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return event

    def list(self) -> list[AuditEvent]:
        return list(self.events)


@dataclass
class MeetingDomainStore:
    """Small in-memory store used by domain tests and early services.

    RFC-0001: The store keeps repositories, rule engine, and state revision
    together so all write paths can update state_revision atomically.
    """

    rooms: InMemoryRoomRepository = field(default_factory=InMemoryRoomRepository)
    composites: InMemoryCompositeRoomRepository = field(default_factory=InMemoryCompositeRoomRepository)
    rules: InMemoryRuleRepository = field(default_factory=InMemoryRuleRepository)
    bookings: InMemoryBookingRepository = field(default_factory=InMemoryBookingRepository)
    booking_windows: dict[str, list[object]] = field(default_factory=dict)
    opening_schedules: dict[str, list[object]] = field(default_factory=dict)
    idempotency_results: dict[str, str] = field(default_factory=dict)
    audits: InMemoryAuditRepository = field(default_factory=InMemoryAuditRepository)
    state_revision: StateRevisionStore = field(default_factory=StateRevisionStore)
    rule_engine: MeetingRuleEngine = field(init=False)

    def __post_init__(self) -> None:
        self.rule_engine = MeetingRuleEngine(self)

    @contextmanager
    def transaction(self):
        """No-op transaction for in-memory tests."""

        yield

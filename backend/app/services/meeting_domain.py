"""Domain services for the local meeting-room system.

RFC-0001: Meeting room domain model and rule engine.
Services coordinate repositories, the rule engine, state revision, audit events,
and idempotency while keeping domain rules out of API and NL layers.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

from app.domain.booking import Booking, BookingTimeWindow
from app.domain.common import (
    AuditEvent,
    AvailabilityRequest,
    AvailabilityResult,
    BookingStatus,
    ConflictCode,
    Recurrence,
    RuleTimeWindow,
    RuleType,
    TargetType,
    TimeWindow,
    days_between,
    new_id,
)
from app.domain.composite_room import CompositeRoom
from app.domain.room import Room
from app.domain.rule import RoomRule
from app.domain.rule_engine import MeetingRuleEngine


class AuditWriter(Protocol):
    def save(self, event: AuditEvent) -> AuditEvent: ...


class StateRevisionWriter(Protocol):
    def current(self) -> int: ...

    def increment(self) -> int: ...


@dataclass(frozen=True, slots=True)
class RuleUpsertRequest:
    """Structured request to create or update a room rule."""

    target_type: TargetType
    target_id: str
    rule_type: RuleType
    time_windows: list[RuleTimeWindow]
    reason: str
    actor_id: str
    match_key: str | None = None
    rule_id: str | None = None
    protected: bool = False
    expected_state_revision: int | None = None


@dataclass(frozen=True, slots=True)
class RuleUpsertResult:
    """Result returned after a rule create/update operation."""

    rule: RoomRule
    old_rule: RoomRule | None
    matched_rule_id: str | None
    state_revision: int


@dataclass(frozen=True, slots=True)
class RuleDeleteResult:
    """Result returned after a rule delete operation."""

    deleted_rule_id: str
    state_revision: int


@dataclass(frozen=True, slots=True)
class RoomUpsertRequest:
    """Structured request to create or update a room."""

    name: str
    room_type: str
    capacity: int
    location: str
    equipment: list[str] | None = None
    position: dict[str, float] | None = None
    active: bool = True
    room_id: str | None = None
    expected_state_revision: int | None = None


@dataclass(frozen=True, slots=True)
class RoomUpsertResult:
    """Result returned after a room create/update operation."""

    room: Room
    state_revision: int


@dataclass(frozen=True, slots=True)
class OpeningScheduleUpsertRequest:
    """Structured request to create or update an opening schedule."""

    room_id: str
    weekday: int
    start_time: time
    end_time: time
    actor_id: str
    expected_state_revision: int | None = None


@dataclass(frozen=True, slots=True)
class OpeningScheduleUpsertResult:
    """Result returned after an opening-schedule write operation."""

    schedule: object
    state_revision: int


@dataclass(frozen=True, slots=True)
class BookingCreateRequest:
    """Structured request to create a booking."""

    target_type: TargetType
    target_id: str
    start_at: datetime
    end_at: datetime
    title: str
    actor_id: str
    organizer_id: str
    attendees: list[str] | None = None
    description: str | None = None
    idempotency_key: str | None = None
    expected_state_revision: int | None = None


@dataclass(frozen=True, slots=True)
class BookingCreateResult:
    """Result returned after a booking create operation."""

    booking: Booking | None
    time_windows: list[TimeWindow]
    availability: AvailabilityResult
    state_revision: int
    idempotency_replayed: bool = False


@dataclass(frozen=True, slots=True)
class BookingUpdateRequest:
    """Structured request to update an existing booking."""

    target_type: TargetType | None = None
    target_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    title: str | None = None
    organizer_id: str | None = None
    attendees: list[str] | None = None
    description: str | None = None
    reason: str | None = None
    expected_state_revision: int | None = None


@dataclass(frozen=True, slots=True)
class BookingUpdateResult:
    """Result returned after a booking update operation."""

    booking: Booking
    old_time_windows: list[TimeWindow]
    new_time_windows: list[TimeWindow]
    availability: AvailabilityResult
    affected_bookings: list[dict[str, Any]]
    state_revision: int
    moved: bool


@dataclass(frozen=True, slots=True)
class BookingCancelResult:
    """Result returned after a booking cancel operation."""

    booking: Booking
    time_windows: list[TimeWindow]
    state_revision: int


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """Rule matching metadata used by continuous modification flows."""

    rule_id: str | None
    match_key: str | None
    similar: bool = False


class MeetingDomainInitializer:
    """Initialize RFC-0001 fixed spaces, opening schedules, and protected rules."""

    def __init__(self, initializer: "MeetingDomainService") -> None:
        self.initializer = initializer

    def initialize(self, *, now: datetime | None = None) -> None:
        """Idempotently initialize the default local meeting-room state."""

        now = now or datetime.now()
        self.initializer._initialize_default_rooms(now)
        self.initializer._initialize_default_composites(now)
        self.initializer._initialize_default_opening_schedules()
        self.initializer._initialize_default_rules(now)


class MeetingDomainService:
    """Application-level domain service for RFC-0001.

    RFC-0001: This service is the single write path for room state, rules,
    bookings, cancellation, booking updates, calendar slices, floor-plan state,
    and state_revision. SQLite-backed stores must run these methods inside a
    transaction; the in-memory store provides a no-op transaction for tests.
    """

    def __init__(self, store: Any) -> None:
        self.store = store
        self.rule_engine = getattr(store, "rule_engine", MeetingRuleEngine(store))
        self.initializer = MeetingDomainInitializer(self)
        self._state_revision = getattr(store, "state_revision", None)

    @contextmanager
    def _write_transaction(self) -> Any:
        transaction = getattr(self.store, "transaction", None)
        if transaction is not None:
            with transaction():
                yield
        else:
            yield

    def initialize_default_state(self, *, now: datetime | None = None) -> None:
        """Initialize the default RFC-0001 domain state idempotently."""

        now = now or datetime.now()
        with self._write_transaction():
            self.initializer.initialize(now=now)

    def get_room_detail(self, target_id: str) -> dict[str, Any] | None:
        """Return room detail including schedules and fixed-rule summaries."""

        room = self.store.rooms.get(target_id)
        if room is None:
            return None
        schedules = self._list_opening_schedules(target_id)
        rules = self.store.rules.list_for_target(TargetType.ROOM, target_id, include_protected=True)
        return {
            "target_type": TargetType.ROOM.value,
            "room": room,
            "opening_schedules": schedules,
            "fixed_rule_summary": [rule.to_summary() for rule in rules if rule.protected],
        }

    def get_composite_detail(self, target_id: str) -> dict[str, Any] | None:
        """Return composite detail including member-room summaries."""

        composite = self.store.composites.get(target_id)
        if composite is None:
            return None
        return {
            "target_type": TargetType.COMPOSITE.value,
            "composite": composite,
            "member_rooms": [self.store.rooms.get(room_id) for room_id in composite.member_room_ids if self.store.rooms.get(room_id)],
        }

    def check_availability(self, request: AvailabilityRequest) -> AvailabilityResult:
        """Delegate availability checks to the single rule-engine boundary."""

        return self.rule_engine.check_availability(request)

    def list_rules(self, *, target_type: TargetType | None = None, target_id: str | None = None, include_protected: bool = True) -> list[dict[str, Any]]:
        """Return structured rules for API and calendar consumers."""

        rules = self.store.rules.list_all(include_protected=include_protected)
        if target_type is not None:
            rules = [rule for rule in rules if rule.target_type == target_type]
        if target_id is not None:
            rules = [rule for rule in rules if rule.target_id == target_id]
        return [self._rule_to_dict(rule) for rule in rules]

    def list_bookings(self, *, target_type: TargetType | None = None, target_id: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        """Return structured bookings for calendar and detail views."""

        bookings = self.store.bookings.list_active() if active_only else self.store.bookings.list()
        if target_type is not None:
            bookings = [booking for booking in bookings if booking.target_type == target_type]
        if target_id is not None:
            bookings = [booking for booking in bookings if booking.target_id == target_id]
        return [self._booking_to_dict(booking) for booking in bookings]

    def get_booking_detail(self, booking_id: str) -> dict[str, Any] | None:
        """Return booking detail with its active time windows."""

        booking = self.store.bookings.get(booking_id)
        if booking is None:
            return None
        return {
            "booking": booking,
            "time_windows": self._booking_windows(booking.id),
            "state_revision": self.current_state_revision(),
        }

    def upsert_room(self, request: RoomUpsertRequest, *, now: datetime | None = None) -> RoomUpsertResult:
        """Create or update a room while preserving RFC-0001 fixed-space invariants."""

        now = now or datetime.now()
        with self._write_transaction():
            self._check_expected_state_revision(request.expected_state_revision)
            room_id = request.room_id or new_id("room")
            existing = self.store.rooms.get(room_id)
            if existing is not None:
                room_id = existing.id
            if room_id in {"activity-room", "meeting-room-1", "meeting-room-2", "503", "505", "506"}:
                fixed = {
                    "activity-room": ("activity", 20, "5F"),
                    "meeting-room-1": ("medium", 12, "5F"),
                    "meeting-room-2": ("medium", 12, "5F"),
                    "503": ("small", 4, "5F"),
                    "505": ("small", 4, "5F"),
                    "506": ("small", 4, "5F"),
                }[room_id]
                if request.room_type != fixed[0] or request.capacity != fixed[1] or request.location != fixed[2]:
                    raise ValueError("fixed room invariant cannot be changed by ordinary room upsert")
            room = Room(
                id=room_id,
                name=request.name,
                room_type=request.room_type,
                capacity=request.capacity,
                location=request.location,
                equipment=list(request.equipment or []),
                position=dict(request.position or {}),
                active=request.active,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self.store.rooms.save(room)
            self._record_audit("room_upserted", "system", TargetType.ROOM, room.id, {"room_id": room.id, "old_room_id": existing.id if existing else None}, now)
            revision = self._increment_state_revision()
            return RoomUpsertResult(room=room, state_revision=revision)

    def upsert_opening_schedule(self, request: OpeningScheduleUpsertRequest, *, now: datetime | None = None) -> OpeningScheduleUpsertResult:
        """Create or replace one opening schedule for a room."""

        now = now or datetime.now()
        with self._write_transaction():
            self._check_expected_state_revision(request.expected_state_revision)
            from app.domain.common import OpeningSchedule

            schedule = OpeningSchedule(
                room_id=request.room_id,
                weekday=request.weekday,
                start_time=request.start_time,
                end_time=request.end_time,
            )
            schedules = self._list_opening_schedules(request.room_id)
            schedules = [
                item
                for item in schedules
                if not (item.weekday == schedule.weekday and item.start_time == schedule.start_time and item.end_time == schedule.end_time)
            ]
            schedules.append(schedule)
            self._save_opening_schedules(request.room_id, schedules)
            self._record_audit("opening_schedule_upserted", request.actor_id, TargetType.ROOM, request.room_id, self._schedule_to_dict(schedule), now)
            revision = self._increment_state_revision()
            return OpeningScheduleUpsertResult(schedule=schedule, state_revision=revision)

    def update_booking(self, booking_id: str, request: BookingUpdateRequest, *, now: datetime | None = None) -> BookingUpdateResult:
        """Move or update an existing booking after checking the new window is available."""

        now = now or datetime.now()
        with self._write_transaction():
            self._check_expected_state_revision(request.expected_state_revision)
            booking = self.store.bookings.get(booking_id)
            if booking is None:
                raise ValueError(f"booking {booking_id} not found")
            if not booking.is_active:
                raise ValueError(f"booking {booking_id} is not active")
            old_windows = self._booking_windows(booking.id)
            new_target_type = request.target_type or booking.target_type
            new_target_id = request.target_id or booking.target_id
            new_start_at = request.start_at if request.start_at is not None else (old_windows[0].start_at if old_windows else now)
            new_end_at = request.end_at if request.end_at is not None else (old_windows[-1].end_at if old_windows else now + timedelta(hours=1))
            availability = self.rule_engine.check_availability(
                AvailabilityRequest(
                    target_type=new_target_type,
                    target_id=new_target_id,
                    start_at=new_start_at,
                    end_at=new_end_at,
                    ignore_booking_id=booking.id,
                )
            )
            if not availability.available:
                raise BookingConflictError(availability)
            if request.title is not None:
                booking.title = request.title
            if request.organizer_id is not None:
                booking.organizer_id = request.organizer_id
            if request.attendees is not None:
                booking.attendees = list(request.attendees)
            if request.description is not None:
                booking.description = request.description
            booking.target_type = new_target_type
            booking.target_id = new_target_id
            booking.updated_at = now
            self.store.bookings.save(booking)
            new_windows = [TimeWindow(new_start_at, new_end_at)]
            self._save_booking_windows(booking.id, new_windows)
            self._record_audit("booking_updated", booking.actor_id, booking.target_type, booking.target_id, {"booking_id": booking.id, "reason": request.reason}, now)
            revision = self._increment_state_revision()
            return BookingUpdateResult(
                booking=booking,
                old_time_windows=old_windows,
                new_time_windows=new_windows,
                availability=availability,
                affected_bookings=[],
                state_revision=revision,
                moved=old_windows != new_windows,
            )

    def list_available_targets(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        capacity: int | None = None,
        equipment: list[str] | None = None,
        room_type: str | None = None,
        allow_composite: bool = True,
    ) -> dict[str, Any]:
        """Return available rooms/composites and unavailable reasons for a time window."""

        request = AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="",
            start_at=start_at,
            end_at=end_at,
            capacity=capacity,
            equipment=tuple(equipment or []),
            room_type=room_type,
            allow_composite=allow_composite,
        )
        available: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        for room in self.store.rooms.list():
            if room_type is not None and room.type != room_type:
                continue
            if capacity is not None and room.capacity < capacity:
                continue
            if equipment and not room.has_equipment(equipment):
                continue
            result = self.rule_engine.check_availability(
                AvailabilityRequest(
                    target_type=TargetType.ROOM,
                    target_id=room.id,
                    start_at=start_at,
                    end_at=end_at,
                    capacity=capacity,
                    equipment=tuple(equipment or []),
                    room_type=room_type,
                    allow_composite=allow_composite,
                )
            )
            if result.available:
                available.append({"target_type": TargetType.ROOM.value, "target_id": room.id, "name": room.name})
            else:
                unavailable.append(
                    {
                        "target_type": TargetType.ROOM.value,
                        "target_id": room.id,
                        "name": room.name,
                        "conflicts": [code.value for code in result.conflicts],
                        "unavailable_reasons": result.unavailable_reasons,
                    }
                )
        if allow_composite:
            for composite in self.store.composites.list():
                if capacity is not None and composite.capacity < capacity:
                    continue
                if equipment and not composite.has_equipment(equipment):
                    continue
                result = self.rule_engine.check_availability(
                    AvailabilityRequest(
                        target_type=TargetType.COMPOSITE,
                        target_id=composite.id,
                        start_at=start_at,
                        end_at=end_at,
                        capacity=capacity,
                        equipment=tuple(equipment or []),
                        allow_composite=True,
                    )
                )
                if result.available:
                    available.append({"target_type": TargetType.COMPOSITE.value, "target_id": composite.id, "name": composite.name})
                else:
                    unavailable.append(
                        {
                            "target_type": TargetType.COMPOSITE.value,
                            "target_id": composite.id,
                            "name": composite.name,
                            "conflicts": [code.value for code in result.conflicts],
                            "unavailable_reasons": result.unavailable_reasons,
                        }
                    )
        return {
            "request": request,
            "available": available,
            "unavailable": unavailable,
            "state_revision": self.current_state_revision(),
        }

    def get_calendar_events(self, *, target_type: TargetType | None, target_id: str | None, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        """Return calendar events for rules and bookings in a time range."""

        events: list[dict[str, Any]] = []
        rules = self.store.rules.list_all(include_protected=True)
        for rule in rules:
            if target_type is not None and rule.target_type != target_type:
                continue
            if target_id is not None and rule.target_id != target_id:
                continue
            for window in rule.time_windows:
                for event_window in self._calendar_rule_windows(window, start_at, end_at):
                    events.append(
                        {
                            "event_type": "rule",
                            "target_type": rule.target_type.value,
                            "target_id": rule.target_id,
                            "start_at": event_window.start_at,
                            "end_at": event_window.end_at,
                            "rule_id": rule.id,
                            "rule_type": rule.rule_type.value,
                            "reason": rule.reason,
                            "protected": rule.protected,
                        }
                    )
        for booking in self.store.bookings.list_active():
            if target_type is not None and booking.target_type != target_type:
                continue
            if target_id is not None and booking.target_id != target_id:
                continue
            for window in self._booking_windows(booking.id):
                if TimeWindow(start_at, end_at).overlaps(window):
                    events.append(
                        {
                            "event_type": "booking",
                            "target_type": booking.target_type.value,
                            "target_id": booking.target_id,
                            "start_at": window.start_at,
                            "end_at": window.end_at,
                            "booking_id": booking.id,
                            "title": booking.title,
                        }
                    )
        return events

    def get_floor_plan_state(self, *, floor: str = "5F", at: datetime) -> list[dict[str, Any]]:
        """Return floor-plan room states at one instant."""

        states: list[dict[str, Any]] = []
        for room in self.store.rooms.list():
            if room.location != floor or not room.active:
                continue
            state = "available"
            reason = ""
            for rule in self.store.rules.list_for_target(TargetType.ROOM, room.id, include_protected=True):
                if rule.matches(at, at + timedelta(minutes=1)):
                    state = "unavailable"
                    reason = rule.reason
                    break
            if state == "available":
                request = AvailabilityRequest(
                    target_type=TargetType.ROOM,
                    target_id=room.id,
                    start_at=at,
                    end_at=at + timedelta(minutes=1),
                )
                result = self.rule_engine.check_availability(request)
                if not result.available:
                    booked_codes = {ConflictCode.OVERLAPPING_BOOKING, ConflictCode.OVERLAPPING_COMPOSITE_BOOKING}
                    state = "booked" if set(result.conflicts) <= booked_codes else "unavailable"
                    reason = result.unavailable_reasons[0] if result.unavailable_reasons else ""
            states.append(
                {
                    "target_type": TargetType.ROOM.value,
                    "target_id": room.id,
                    "name": room.name,
                    "position": room.position,
                    "status": state,
                    "reason": reason,
                }
            )
        return states

    def upsert_rule(self, request: RuleUpsertRequest, *, now: datetime | None = None, match: RuleMatch | None = None) -> RuleUpsertResult:
        """Create or update a rule, preserving identity for continuous edits."""

        now = now or datetime.now()
        with self._write_transaction():
            self._check_expected_state_revision(request.expected_state_revision)
            match = match or self.match_rule(request)
            if match.rule_id is not None:
                existing = self.store.rules.get(match.rule_id)
                if existing is None:
                    raise ValueError(f"rule {match.rule_id} not found")
                if existing.protected and not request.protected:
                    raise ProtectedRuleError(existing)
                if existing.protected:
                    request = RuleUpsertRequest(
                        target_type=existing.target_type,
                        target_id=existing.target_id,
                        rule_type=existing.rule_type,
                        reason=existing.reason,
                        actor_id=request.actor_id,
                        protected=True,
                        match_key=existing.match_key,
                        time_windows=existing.time_windows,
                        expected_state_revision=request.expected_state_revision,
                    )
                old_rule = existing
                rule = RoomRule(
                    id=existing.id,
                    target_type=request.target_type,
                    target_id=request.target_id,
                    rule_type=request.rule_type,
                    match_key=request.match_key or existing.match_key,
                    reason=request.reason,
                    actor_id=request.actor_id,
                    protected=request.protected,
                    time_windows=list(request.time_windows),
                    created_at=existing.created_at,
                    updated_at=now,
                )
            else:
                old_rule = None
                rule = RoomRule(
                    id=new_id("rule"),
                    target_type=request.target_type,
                    target_id=request.target_id,
                    rule_type=request.rule_type,
                    match_key=request.match_key or self._default_match_key(request),
                    reason=request.reason,
                    actor_id=request.actor_id,
                    protected=request.protected,
                    time_windows=list(request.time_windows),
                    created_at=now,
                    updated_at=now,
                )
            self.store.rules.save(rule)
            self._record_audit("rule_upserted", request.actor_id, request.target_type, request.target_id, {"rule_id": rule.id, "old_rule_id": old_rule.id if old_rule else None}, now)
            revision = self._increment_state_revision()
            return RuleUpsertResult(rule=rule, old_rule=old_rule, matched_rule_id=match.rule_id, state_revision=revision)

    def delete_rule(self, rule_id: str, *, actor_id: str, expected_state_revision: int | None = None, now: datetime | None = None) -> RuleDeleteResult:
        """Delete a rule unless it is a protected fixed rule."""

        now = now or datetime.now()
        with self._write_transaction():
            self._check_expected_state_revision(expected_state_revision)
            rule = self.store.rules.get(rule_id)
            if rule is None:
                raise ValueError(f"rule {rule_id} not found")
            if rule.protected:
                raise ProtectedRuleError(rule)
            self.store.rules.delete(rule_id)
            self._record_audit("rule_deleted", actor_id, rule.target_type, rule.target_id, {"rule_id": rule_id}, now)
            return RuleDeleteResult(deleted_rule_id=rule_id, state_revision=self._increment_state_revision())

    def create_booking(self, request: BookingCreateRequest, *, now: datetime | None = None) -> BookingCreateResult:
        """Create a confirmed booking after rule-engine conflict validation."""

        now = now or datetime.now()
        if request.idempotency_key:
            replay = self._load_idempotency_result(request.idempotency_key)
            if replay is not None:
                response = replay["response_body"]
                booking = self.store.bookings.get(response["booking_id"])
                if booking is None:
                    raise ValueError("idempotency replay target booking not found")
                return BookingCreateResult(
                    booking=booking,
                    time_windows=self._booking_windows(booking.id),
                    availability=self._availability_from_snapshot(response["availability"]),
                    state_revision=int(response["state_revision"]),
                    idempotency_replayed=True,
                )
        with self._write_transaction():
            self._check_expected_state_revision(request.expected_state_revision)
            availability = self.rule_engine.check_availability(
                AvailabilityRequest(
                    target_type=request.target_type,
                    target_id=request.target_id,
                    start_at=request.start_at,
                    end_at=request.end_at,
                )
            )
            if not availability.available:
                return BookingCreateResult(
                    booking=None,
                    time_windows=[],
                    availability=availability,
                    state_revision=self.current_state_revision(),
                )
            booking = Booking(
                id=new_id("booking"),
                target_type=request.target_type,
                target_id=request.target_id,
                title=request.title,
                actor_id=request.actor_id,
                organizer_id=request.organizer_id,
                attendees=list(request.attendees or []),
                description=request.description,
                status=BookingStatus.CONFIRMED,
                idempotency_key=request.idempotency_key,
                created_at=now,
                updated_at=now,
            )
            self.store.bookings.save(booking)
            window = TimeWindow(request.start_at, request.end_at)
            self._save_booking_windows(booking.id, [window])
            self._record_audit("booking_created", request.actor_id, request.target_type, request.target_id, {"booking_id": booking.id}, now)
            revision = self._increment_state_revision()
            if request.idempotency_key:
                self._save_idempotency_result(
                    request.idempotency_key,
                    "create_booking",
                    revision,
                    {
                        "booking_id": booking.id,
                        "state_revision": revision,
                        "availability": self._availability_to_snapshot(availability),
                        "time_windows": [self._time_window_to_snapshot(window)],
                    },
                    now,
                )
            return BookingCreateResult(booking=booking, time_windows=[window], availability=availability, state_revision=revision)

    def cancel_booking(self, booking_id: str, *, reason: str | None = None, cancelled_by: str | None = None, now: datetime | None = None) -> BookingCancelResult:
        """Cancel an active booking and release its time windows."""

        now = now or datetime.now()
        with self._write_transaction():
            booking = self.store.bookings.get(booking_id)
            if booking is None:
                raise ValueError(f"booking {booking_id} not found")
            if not booking.is_active:
                raise ValueError(f"booking {booking_id} is not active")
            windows = self._booking_windows(booking_id)
            booking.cancel(reason=reason, cancelled_by=cancelled_by, updated_at=now)
            self.store.bookings.save(booking)
            self._save_booking_windows(booking_id, [])
            self._record_audit("booking_cancelled", cancelled_by or booking.actor_id, booking.target_type, booking.target_id, {"booking_id": booking.id, "reason": reason}, now)
            revision = self._increment_state_revision()
            return BookingCancelResult(booking=booking, time_windows=windows, state_revision=revision)

    def match_rule(self, request: RuleUpsertRequest) -> RuleMatch:
        """Match a rule by explicit id, match key, or similarity."""

        if request.rule_id:
            return RuleMatch(rule_id=request.rule_id, match_key=request.match_key)
        if request.match_key:
            candidates = [
                rule
                for rule in self.store.rules.list_all(include_protected=True)
                if rule.match_key == request.match_key
            ]
            if len(candidates) == 1:
                return RuleMatch(rule_id=candidates[0].id, match_key=request.match_key)
        candidates = [
            rule
            for rule in self.store.rules.list_all(include_protected=False)
            if rule.target_type == request.target_type
            and rule.target_id == request.target_id
            and rule.rule_type == request.rule_type
            and not rule.protected
        ]
        request_dates = {window.start_at.date() for window in request.time_windows if window.start_at is not None}
        if request_dates:
            candidates = [rule for rule in candidates if any(w.start_at.date() in request_dates for w in rule.time_windows if w.start_at is not None)]
        if len(candidates) == 1:
            return RuleMatch(rule_id=candidates[0].id, match_key=request.match_key, similar=True)
        return RuleMatch(rule_id=None, match_key=request.match_key)

    def current_state_revision(self) -> int:
        """Return the current lightweight state revision."""

        return self._state_revision.current() if self._state_revision else 0

    def _initialize_default_rooms(self, now: datetime) -> None:
        defaults = [
            Room("activity-room", "活动室", "activity", 20, "5F", ["projector", "whiteboard"], {"x": 40, "y": 40, "width": 100, "height": 60}, True, now, now),
            Room("meeting-room-1", "会议室一", "medium", 12, "5F", ["projector", "whiteboard"], {"x": 160, "y": 40, "width": 100, "height": 60}, True, now, now),
            Room("meeting-room-2", "会议室二", "medium", 12, "5F", ["projector", "whiteboard"], {"x": 280, "y": 40, "width": 100, "height": 60}, True, now, now),
            Room("503", "503", "small", 4, "5F", ["whiteboard"], {"x": 40, "y": 120, "width": 80, "height": 50}, True, now, now),
            Room("504", "504", "small", 4, "5F", ["whiteboard"], {"x": 140, "y": 120, "width": 80, "height": 50}, True, now, now),
            Room("505", "505", "small", 4, "5F", ["whiteboard"], {"x": 240, "y": 120, "width": 80, "height": 50}, True, now, now),
            Room("506", "506", "small", 4, "5F", ["whiteboard"], {"x": 340, "y": 120, "width": 80, "height": 50}, True, now, now),
        ]
        for room in defaults:
            existing = self.store.rooms.get(room.id)
            if existing is None:
                self.store.rooms.save(room)

    def _initialize_default_composites(self, now: datetime) -> None:
        composite = CompositeRoom(
            id="meeting-room-1-2",
            name="会议室一+会议室二",
            member_room_ids=["meeting-room-1", "meeting-room-2"],
            capacity=24,
            equipment=["projector", "whiteboard"],
            active=True,
            created_at=now,
            updated_at=now,
        )
        existing = self.store.composites.get(composite.id)
        if existing is None:
            self.store.composites.save(composite)
        else:
            existing.update_from(
                name=composite.name,
                member_room_ids=composite.member_room_ids,
                capacity=composite.capacity,
                equipment=composite.equipment,
                updated_at=now,
            )
            self.store.composites.save(existing)

    def _initialize_default_opening_schedules(self) -> None:
        from app.domain.common import OpeningSchedule

        default_room_ids = ["activity-room", "meeting-room-1", "meeting-room-2", "503", "504", "505", "506"]
        for room_id in default_room_ids:
            schedules = self._list_opening_schedules(room_id)
            schedules = [
                schedule
                for schedule in schedules
                if not (schedule.weekday in range(5) and schedule.start_time == time(9) and schedule.end_time == time(18))
            ]
            for weekday in range(5):
                schedules.append(OpeningSchedule(room_id=room_id, weekday=weekday, start_time=time(9), end_time=time(18)))
            self._save_opening_schedules(room_id, schedules)

    def _initialize_default_rules(self, now: datetime) -> None:
        lunch_rule = self._default_lunch_rule(now)
        existing_lunch = self.store.rules.get(lunch_rule.id)
        if existing_lunch is None:
            self.store.rules.save(lunch_rule)
        else:
            existing_lunch.update_from(
                rule_type=lunch_rule.rule_type,
                match_key=lunch_rule.match_key,
                reason=lunch_rule.reason,
                time_windows=lunch_rule.time_windows,
                updated_at=now,
            )
            existing_lunch.target_type = lunch_rule.target_type
            existing_lunch.target_id = lunch_rule.target_id
            existing_lunch.actor_id = lunch_rule.actor_id
            existing_lunch.protected = lunch_rule.protected
            self.store.rules.save(existing_lunch)

        tuesday_rule = self._default_505_tuesday_rule(now)
        existing_tuesday = self.store.rules.get(tuesday_rule.id)
        if existing_tuesday is None:
            self.store.rules.save(tuesday_rule)
        else:
            existing_tuesday.update_from(
                rule_type=tuesday_rule.rule_type,
                match_key=tuesday_rule.match_key,
                reason=tuesday_rule.reason,
                time_windows=tuesday_rule.time_windows,
                updated_at=now,
            )
            existing_tuesday.target_type = tuesday_rule.target_type
            existing_tuesday.target_id = tuesday_rule.target_id
            existing_tuesday.actor_id = tuesday_rule.actor_id
            existing_tuesday.protected = tuesday_rule.protected
            self.store.rules.save(existing_tuesday)

    def _default_lunch_rule(self, now: datetime) -> RoomRule:
        return RoomRule(
            id="rule-activity-lunch",
            target_type=TargetType.ROOM,
            target_id="activity-room",
            rule_type=RuleType.FIXED_UNAVAILABLE,
            match_key="activity-room:fixed_unavailable:lunch",
            reason="午餐占用",
            actor_id="system",
            protected=True,
            time_windows=[
                RuleTimeWindow(
                    recurrence=Recurrence.every_weekday(time(12), time(13)),
                )
            ],
            created_at=now,
            updated_at=now,
        )

    def _default_505_tuesday_rule(self, now: datetime) -> RoomRule:
        return RoomRule(
            id="rule-505-tuesday",
            target_type=TargetType.ROOM,
            target_id="505",
            rule_type=RuleType.WEEKLY_UNAVAILABLE,
            match_key="505:weekly_unavailable:tuesday",
            reason="周二全天不可用",
            actor_id="system",
            protected=True,
            time_windows=[
                RuleTimeWindow(
                    recurrence=Recurrence.weekly(1, time(0), time(23, 59, 59, 999999)),
                )
            ],
            created_at=now,
            updated_at=now,
        )

    def _rule_to_dict(self, rule: RoomRule) -> dict[str, Any]:
        return {
            "id": rule.id,
            "target_type": rule.target_type.value,
            "target_id": rule.target_id,
            "rule_type": rule.rule_type.value,
            "match_key": rule.match_key,
            "reason": rule.reason,
            "actor_id": rule.actor_id,
            "protected": rule.protected,
            "time_windows": [self._rule_time_window_to_dict(window) for window in rule.time_windows],
            "created_at": rule.created_at.isoformat() if rule.created_at else None,
            "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        }

    def _rule_time_window_to_dict(self, window: RuleTimeWindow) -> dict[str, Any]:
        recurrence = None
        if window.recurrence is not None:
            recurrence = {
                "weekdays": list(window.recurrence.weekdays),
                "start_time": window.recurrence.start_time.isoformat(),
                "end_time": window.recurrence.end_time.isoformat(),
                "end_date": window.recurrence.end_date.isoformat() if window.recurrence.end_date else None,
            }
        return {
            "start_at": window.start_at.isoformat() if window.start_at else None,
            "end_at": window.end_at.isoformat() if window.end_at else None,
            "recurrence": recurrence,
        }

    def _booking_to_dict(self, booking: Booking) -> dict[str, Any]:
        return {
            "booking": booking,
            "target_type": booking.target_type.value,
            "target_id": booking.target_id,
            "title": booking.title,
            "actor_id": booking.actor_id,
            "organizer_id": booking.organizer_id,
            "attendees": list(booking.attendees),
            "description": booking.description,
            "status": booking.status.value,
            "idempotency_key": booking.idempotency_key,
            "created_at": booking.created_at.isoformat() if booking.created_at else None,
            "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
        }

    def _schedule_to_dict(self, schedule: object) -> dict[str, Any]:
        return {
            "room_id": schedule.room_id,
            "weekday": schedule.weekday,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat(),
        }

    def _list_opening_schedules(self, room_id: str) -> list[Any]:
        repository = getattr(self.store, "opening_schedules", {})
        if hasattr(repository, "list_for_room"):
            return list(repository.list_for_room(room_id))
        return list(repository.get(room_id, []))

    def _save_opening_schedules(self, room_id: str, schedules: list[Any]) -> None:
        repository = getattr(self.store, "opening_schedules", {})
        if hasattr(repository, "clear_for_room"):
            repository.clear_for_room(room_id)
            for schedule in schedules:
                repository.save(schedule)
            return
        repository[room_id] = list(schedules)

    def _booking_windows(self, booking_id: str) -> list[TimeWindow]:
        repository = getattr(self.store, "booking_windows", {})
        if hasattr(repository, "list_for_booking"):
            windows = repository.list_for_booking(booking_id)
        else:
            windows = repository.get(booking_id, [])
        return [window for window in windows if isinstance(window, TimeWindow)]

    def _save_booking_windows(self, booking_id: str, windows: list[TimeWindow]) -> None:
        repository = getattr(self.store, "booking_windows", {})
        if hasattr(repository, "clear") and not isinstance(repository, dict):
            repository.clear(booking_id)
            for window in windows:
                repository.save(booking_id, window)
            return
        repository[booking_id] = list(windows)

    def _availability_to_snapshot(self, availability: AvailabilityResult) -> dict[str, Any]:
        return {
            "target_type": availability.target_type.value,
            "target_id": availability.target_id,
            "start_at": availability.start_at.isoformat(),
            "end_at": availability.end_at.isoformat(),
            "available": availability.available,
            "checks": [
                {
                    "check_type": check.check_type.value,
                    "passed": check.passed,
                    "message": check.message,
                    "conflict_code": check.conflict_code.value if check.conflict_code else None,
                    "details": check.details,
                }
                for check in availability.checks
            ],
            "conflicts": [conflict.value for conflict in availability.conflicts],
            "unavailable_reasons": list(availability.unavailable_reasons),
        }

    def _availability_from_snapshot(self, snapshot: dict[str, Any]) -> AvailabilityResult:
        from app.domain.common import CheckResult, CheckType

        return AvailabilityResult(
            target_type=TargetType(snapshot["target_type"]),
            target_id=snapshot["target_id"],
            start_at=datetime.fromisoformat(snapshot["start_at"]),
            end_at=datetime.fromisoformat(snapshot["end_at"]),
            available=bool(snapshot["available"]),
            checks=[
                CheckResult(
                    check_type=CheckType(check["check_type"]),
                    passed=bool(check["passed"]),
                    message=check.get("message"),
                    conflict_code=ConflictCode(check["conflict_code"]) if check.get("conflict_code") else None,
                    details=dict(check.get("details") or {}),
                )
                for check in snapshot.get("checks", [])
            ],
            conflicts=[ConflictCode(conflict) for conflict in snapshot.get("conflicts", [])],
            unavailable_reasons=list(snapshot.get("unavailable_reasons", [])),
        )

    def _time_window_to_snapshot(self, window: TimeWindow) -> dict[str, Any]:
        return {"start_at": window.start_at.isoformat(), "end_at": window.end_at.isoformat()}

    def _time_window_from_snapshot(self, snapshot: dict[str, Any]) -> TimeWindow:
        return TimeWindow(datetime.fromisoformat(snapshot["start_at"]), datetime.fromisoformat(snapshot["end_at"]))

    def _calendar_rule_windows(self, window: RuleTimeWindow, start_at: datetime, end_at: datetime) -> list[TimeWindow]:
        if window.recurrence is None:
            if window.start_at is None or window.end_at is None:
                return []
            absolute = TimeWindow(window.start_at, window.end_at)
            return [absolute] if absolute.overlaps(TimeWindow(start_at, end_at)) else []

        event_windows: list[TimeWindow] = []
        for day in days_between(start_at.date(), end_at.date()):
            if day.weekday() not in window.recurrence.weekdays:
                continue
            if window.recurrence.end_date is not None and day > window.recurrence.end_date:
                continue
            event = TimeWindow(
                datetime.combine(day, window.recurrence.start_time, tzinfo=start_at.tzinfo),
                datetime.combine(day, window.recurrence.end_time, tzinfo=start_at.tzinfo),
            )
            if event.overlaps(TimeWindow(start_at, end_at)):
                event_windows.append(event)
        return event_windows

    def _record_audit(self, event_type: str, actor_id: str, target_type: TargetType | None, target_id: str | None, details: dict[str, Any], now: datetime) -> None:
        self.store.audits.save(
            AuditEvent(
                id=new_id("audit"),
                event_type=event_type,
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
                details=details,
                created_at=now,
            )
        )

    def _increment_state_revision(self) -> int:
        return self._state_revision.increment() if self._state_revision else 0

    def _check_expected_state_revision(self, expected: int | None) -> None:
        if expected is not None and expected != self.current_state_revision():
            raise ValueError("state revision mismatch")

    def _default_match_key(self, request: RuleUpsertRequest) -> str:
        dates = sorted(window.start_at.date().isoformat() for window in request.time_windows if window.start_at is not None)
        return f"{request.target_id}:{request.rule_type.value}:{dates[0] if dates else 'ongoing'}"

    def _load_idempotency_result(self, key: str) -> dict[str, Any] | None:
        repository = getattr(self.store, "idempotency_results", {})
        if isinstance(repository, dict):
            cached = repository.get(key)
            return json.loads(cached) if cached else None
        if hasattr(repository, "get"):
            return repository.get(key)
        cached = repository.get(key)
        return json.loads(cached) if cached else None

    def _save_idempotency_result(self, key: str, operation: str, revision: int, response: dict[str, Any], now: datetime) -> None:
        repository = getattr(self.store, "idempotency_results", {})
        if hasattr(repository, "save"):
            repository.save(key, operation, revision, response, now)
            return
        repository[key] = json.dumps(
            {"operation": operation, "state_revision": revision, "response_body": response, "created_at": now.isoformat(), "updated_at": now.isoformat()},
            ensure_ascii=False,
        )


class ProtectedRuleError(Exception):
    """Raised when ordinary configuration tries to modify a protected rule."""

    def __init__(self, rule: RoomRule) -> None:
        super().__init__(f"protected rule cannot be modified: {rule.id}")
        self.rule = rule

"""Shared domain primitives for the meeting-room system.

RFC-0001: Meeting room domain model and rule engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any
from uuid import uuid4


class TargetType(str, Enum):
    """Target kinds that can be queried or booked."""

    ROOM = "room"
    COMPOSITE = "composite"


class RuleType(str, Enum):
    """Rule categories used by RFC-0001."""

    FIXED_UNAVAILABLE = "fixed_unavailable"
    WEEKLY_UNAVAILABLE = "weekly_unavailable"
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"
    MAINTENANCE = "maintenance"
    ACTIVITY_BLOCK = "activity_block"


class BookingStatus(str, Enum):
    """Booking lifecycle statuses."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    MOVED = "moved"
    CANCELLED_BY_USER = "cancelled_by_user"


class CheckType(str, Enum):
    """Rule-engine check identifiers."""

    TARGET_EXISTS = "target_exists"
    FILTER = "filter"
    OPENING_HOURS = "opening_hours"
    ROOM_RULE = "room_rule"
    COMPOSITE_MEMBER = "composite_member"
    BOOKING_OVERLAP = "booking_overlap"


class ConflictCode(str, Enum):
    """Structured conflict codes returned by the domain layer."""

    TARGET_NOT_FOUND = "target_not_found"
    TARGET_DISABLED = "target_disabled"
    FILTER_MISMATCH = "filter_mismatch"
    OUTSIDE_OPENING_HOURS = "outside_opening_hours"
    FIXED_UNAVAILABLE = "fixed_unavailable"
    WEEKLY_UNAVAILABLE = "weekly_unavailable"
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"
    MAINTENANCE = "maintenance"
    ACTIVITY_BLOCK = "activity_block"
    MEMBER_ROOM_UNAVAILABLE = "member_room_unavailable"
    OVERLAPPING_BOOKING = "overlapping_booking"
    OVERLAPPING_COMPOSITE_BOOKING = "overlapping_composite_booking"


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A half-open time interval used by rules and bookings.

    RFC-0001: Two windows overlap iff start_a < end_b and start_b < end_a.
    """

    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if self.start_at >= self.end_at:
            raise ValueError("time window start_at must be before end_at")

    def overlaps(self, other: "TimeWindow") -> bool:
        """Return True when this window overlaps another half-open window."""

        return self.start_at < other.end_at and other.start_at < self.end_at

    def contains(self, other: "TimeWindow") -> bool:
        """Return True when this window fully contains another window."""

        return self.start_at <= other.start_at and other.end_at <= self.end_at


@dataclass(frozen=True, slots=True)
class Recurrence:
    """Weekly recurrence metadata for a rule time window."""

    weekdays: tuple[int, ...]
    start_time: time
    end_time: time
    end_date: date | None = None

    @classmethod
    def weekly(cls, weekday: int, start_time: time, end_time: time, *, end_date: date | None = None) -> "Recurrence":
        if weekday < 0 or weekday > 6:
            raise ValueError("weekday must be in range 0..6")
        return cls(weekdays=(weekday,), start_time=start_time, end_time=end_time, end_date=end_date)

    @classmethod
    def every_weekday(cls, start_time: time, end_time: time, *, end_date: date | None = None) -> "Recurrence":
        return cls(weekdays=(0, 1, 2, 3, 4), start_time=start_time, end_time=end_time, end_date=end_date)

    def applies_to(self, start_at: datetime, end_at: datetime) -> bool:
        """Return True when a candidate window intersects this weekly recurrence."""

        if self.end_date is not None and start_at.date() > self.end_date:
            return False

        candidate_days = days_between(start_at.date(), end_at.date())
        for day in candidate_days:
            if day.weekday() not in self.weekdays:
                continue
            recurrence_window = TimeWindow(
                datetime.combine(day, self.start_time, tzinfo=start_at.tzinfo),
                datetime.combine(day, self.end_time, tzinfo=end_at.tzinfo),
            )
            if recurrence_window.overlaps(TimeWindow(start_at, end_at)):
                return True
        return False


@dataclass(frozen=True, slots=True)
class RuleTimeWindow:
    """A rule time window, either absolute or weekly recurring."""

    start_at: datetime | None = None
    end_at: datetime | None = None
    recurrence: Recurrence | None = None

    def __post_init__(self) -> None:
        if self.recurrence is None:
            if self.start_at is None or self.end_at is None:
                raise ValueError("absolute rule time windows require start_at and end_at")
            if self.start_at >= self.end_at:
                raise ValueError("rule time window start_at must be before end_at")

    def matches(self, start_at: datetime, end_at: datetime) -> bool:
        """Return True when this rule window overlaps a candidate booking window."""

        if self.recurrence is not None:
            return self.recurrence.applies_to(start_at, end_at)
        assert self.start_at is not None and self.end_at is not None
        return TimeWindow(self.start_at, self.end_at).overlaps(TimeWindow(start_at, end_at))


@dataclass(frozen=True, slots=True)
class OpeningSchedule:
    """Weekly opening schedule for a room."""

    room_id: str
    weekday: int
    start_time: time
    end_time: time

    def __post_init__(self) -> None:
        if self.weekday < 0 or self.weekday > 6:
            raise ValueError("weekday must be in range 0..6")
        if self.start_time >= self.end_time:
            raise ValueError("opening schedule start_time must be before end_time")

    def contains(self, start_at: datetime, end_at: datetime) -> bool:
        """Return True when the candidate window is fully inside this schedule."""

        for day in days_between(start_at.date(), end_at.date()):
            if day.weekday() != self.weekday:
                return False
            window = TimeWindow(
                datetime.combine(day, self.start_time, tzinfo=start_at.tzinfo),
                datetime.combine(day, self.end_time, tzinfo=start_at.tzinfo),
            )
            if not window.contains(TimeWindow(start_at, end_at)):
                return False
        return True


@dataclass(frozen=True, slots=True)
class AvailabilityRequest:
    """Input to the RFC-0001 rule engine."""

    target_type: TargetType
    target_id: str
    start_at: datetime
    end_at: datetime
    capacity: int | None = None
    equipment: tuple[str, ...] = ()
    room_type: str | None = None
    allow_composite: bool = True
    ignore_booking_id: str | None = None


@dataclass(frozen=True, slots=True)
class CheckResult:
    """A single rule-engine check result."""

    check_type: CheckType
    passed: bool
    message: str | None = None
    conflict_code: ConflictCode | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    """Rule-engine decision for a candidate target and time window."""

    target_type: TargetType
    target_id: str
    start_at: datetime
    end_at: datetime
    available: bool
    checks: list[CheckResult]
    conflicts: list[ConflictCode]
    unavailable_reasons: list[str]

    @classmethod
    def available_result(
        cls,
        request: AvailabilityRequest,
        checks: list[CheckResult] | None = None,
    ) -> "AvailabilityResult":
        return cls(
            target_type=request.target_type,
            target_id=request.target_id,
            start_at=request.start_at,
            end_at=request.end_at,
            available=True,
            checks=checks or [],
            conflicts=[],
            unavailable_reasons=[],
        )

    @classmethod
    def unavailable_result(
        cls,
        request: AvailabilityRequest,
        checks: list[CheckResult],
        conflicts: list[ConflictCode],
        unavailable_reasons: list[str],
    ) -> "AvailabilityResult":
        return cls(
            target_type=request.target_type,
            target_id=request.target_id,
            start_at=request.start_at,
            end_at=request.end_at,
            available=False,
            checks=checks,
            conflicts=conflicts,
            unavailable_reasons=unavailable_reasons,
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Minimal audit event recorded by write operations."""

    id: str
    event_type: str
    actor_id: str
    target_type: TargetType | None
    target_id: str | None
    details: dict[str, Any]
    created_at: datetime


def new_id(prefix: str) -> str:
    """Create stable-looking UUID identifiers for in-memory tests and services."""

    return f"{prefix}-{uuid4().hex}"


def days_between(start: date, end: date) -> list[date]:
    """Return all dates from start through end inclusive."""

    from datetime import timedelta

    if start > end:
        return []
    current = start
    days: list[date] = []
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days

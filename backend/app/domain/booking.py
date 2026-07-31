"""Booking domain model.

RFC-0001: Meeting room domain model and rule engine.
Bookings represent confirmed meeting occupancy and release their time windows when cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .common import BookingStatus, TargetType, TimeWindow


@dataclass(slots=True)
class Booking:
    """A meeting booking."""

    id: str
    target_type: TargetType
    target_id: str
    title: str
    actor_id: str
    organizer_id: str
    attendees: list[str] = field(default_factory=list)
    description: str | None = None
    status: BookingStatus = BookingStatus.CONFIRMED
    idempotency_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Return True when the booking still occupies time."""

        return self.status == BookingStatus.CONFIRMED

    def cancel(self, *, reason: str | None = None, cancelled_by: str | None = None, updated_at: datetime) -> None:
        """Cancel the booking and release its time windows."""

        self.status = BookingStatus.CANCELLED_BY_USER if cancelled_by else BookingStatus.CANCELLED
        if reason is not None and self.description:
            self.description = f"{self.description}\n取消原因：{reason}"
        elif reason is not None:
            self.description = f"取消原因：{reason}"
        self.updated_at = updated_at

    def update_from(
        self,
        *,
        title: str | None = None,
        organizer_id: str | None = None,
        attendees: list[str] | None = None,
        description: str | None = None,
        target_type: TargetType | None = None,
        target_id: str | None = None,
        updated_at: datetime,
    ) -> None:
        """Apply a partial booking update in place."""

        if title is not None:
            self.title = title
        if organizer_id is not None:
            self.organizer_id = organizer_id
        if attendees is not None:
            self.attendees = list(attendees)
        if description is not None:
            self.description = description
        if target_type is not None:
            self.target_type = target_type
        if target_id is not None:
            self.target_id = target_id
        self.updated_at = updated_at


@dataclass(frozen=True, slots=True)
class BookingTimeWindow:
    """A single booking time window.

    RFC-0001: This phase only requires single-window bookings, but the model
    keeps time windows separate so future multi-window bookings can be added.
    """

    id: str
    booking_id: str
    time_window: TimeWindow


@dataclass(frozen=True, slots=True)
class BookingDetail:
    """Booking detail with time windows."""

    booking: Booking
    time_windows: list[TimeWindow]

"""Domain tests for RFC-0001 meeting-room model and rule engine."""

from __future__ import annotations

import sqlite3
from datetime import datetime, time

import pytest

from app.domain.common import (
    AvailabilityRequest,
    ConflictCode,
    RuleTimeWindow,
    RuleType,
    TargetType,
    TimeWindow,
)
from app.domain.rule_engine import MeetingRuleEngine
from app.repositories.in_memory import MeetingDomainStore
from app.repositories.sqlite import SQLiteMeetingDomainStore, init_sqlite_schema
from app.services.meeting_domain import BookingCreateRequest, BookingUpdateRequest, MeetingDomainService, ProtectedRuleError, RuleUpsertRequest


def _dt(date: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(f"{date}T{hour:02d}:{minute:02d}:00+08:00")


def _store_with_defaults() -> MeetingDomainStore:
    store = MeetingDomainStore()
    service = MeetingDomainService(store)
    service.initialize_default_state(now=_dt("2026-07-31", 9))
    return store


def _sqlite_store_with_defaults() -> SQLiteMeetingDomainStore:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_sqlite_schema(db)
    store = SQLiteMeetingDomainStore(db)
    service = MeetingDomainService(store)
    service.initialize_default_state(now=_dt("2026-07-31", 9))
    return store


def test_time_windows_overlap_with_half_open_interval() -> None:
    assert TimeWindow(_dt("2026-08-04", 10), _dt("2026-08-04", 11)).overlaps(
        TimeWindow(_dt("2026-08-04", 10, 30), _dt("2026-08-04", 12))
    )
    assert not TimeWindow(_dt("2026-08-04", 10), _dt("2026-08-04", 11)).overlaps(
        TimeWindow(_dt("2026-08-04", 11), _dt("2026-08-04", 12))
    )


def test_activity_room_lunch_fixed_rule_blocks_booking() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="activity-room",
            start_at=_dt("2026-08-04", 12),
            end_at=_dt("2026-08-04", 13),
        )
    )

    assert not result.available
    assert ConflictCode.FIXED_UNAVAILABLE in result.conflicts
    assert "午餐占用" in result.unavailable_reasons


def test_activity_room_non_lunch_time_is_available() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="activity-room",
            start_at=_dt("2026-08-04", 10),
            end_at=_dt("2026-08-04", 11),
        )
    )

    assert result.available
    assert result.conflicts == []


def test_room_505_is_unavailable_on_tuesday() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="505",
            start_at=_dt("2026-08-04", 10),
            end_at=_dt("2026-08-04", 11),
        )
    )

    assert not result.available
    assert ConflictCode.WEEKLY_UNAVAILABLE in result.conflicts
    assert "周二全天不可用" in result.unavailable_reasons


def test_room_505_is_available_on_wednesday() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="505",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
        )
    )

    assert result.available


def test_booking_overlap_uses_half_open_interval() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    now = _dt("2026-08-05", 9)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="重叠测试",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=now,
    )
    assert created.booking.is_active

    overlap = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10, 30),
            end_at=_dt("2026-08-05", 12),
        )
    )
    adjacent = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 11),
            end_at=_dt("2026-08-05", 12),
        )
    )

    assert not overlap.available
    assert ConflictCode.OVERLAPPING_BOOKING in overlap.conflicts
    assert adjacent.available


def test_create_booking_conflict_does_not_save_or_increment_revision() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    first = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="第一预约",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9),
    )
    revision = service.current_state_revision()

    conflict = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10, 30),
            end_at=_dt("2026-08-05", 12),
            title="冲突预约",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9, 30),
    )

    assert conflict.booking is None
    assert conflict.state_revision == revision
    assert len(service.list_bookings(active_only=True)) == 1
    assert service.list_bookings(active_only=True)[0]["booking"].id == first.booking.id


def test_create_booking_idempotency_replay_does_not_duplicate() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    first = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="幂等预约",
            actor_id="alice",
            organizer_id="alice",
            idempotency_key="key-create-503",
        ),
        now=_dt("2026-08-05", 9),
    )
    revision = service.current_state_revision()

    replay = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="幂等预约",
            actor_id="alice",
            organizer_id="alice",
            idempotency_key="key-create-503",
        ),
        now=_dt("2026-08-05", 9, 30),
    )

    assert replay.idempotency_replayed
    assert replay.booking.id == first.booking.id
    assert replay.state_revision == revision
    assert len(service.list_bookings(active_only=True)) == 1


def test_update_booking_moves_window_and_releases_old_slot() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="修改预约",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9),
    )

    updated = service.update_booking(
        created.booking.id,
        BookingUpdateRequest(
            start_at=_dt("2026-08-05", 11),
            end_at=_dt("2026-08-05", 12),
            title="修改预约",
        ),
    )

    assert updated.booking.id == created.booking.id
    assert updated.new_time_windows == [TimeWindow(_dt("2026-08-05", 11), _dt("2026-08-05", 12))]
    assert service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
        )
    ).available


def test_composite_booking_blocks_member_room_bookings() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.COMPOSITE,
            target_id="meeting-room-1-2",
            start_at=_dt("2026-08-07", 14),
            end_at=_dt("2026-08-07", 16),
            title="合并会议室",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-07", 9),
    )
    assert created.booking.is_active

    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="meeting-room-1",
            start_at=_dt("2026-08-07", 15),
            end_at=_dt("2026-08-07", 16),
        )
    )

    assert not result.available
    assert ConflictCode.OVERLAPPING_COMPOSITE_BOOKING in result.conflicts


def test_member_room_booking_blocks_composite_booking() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="meeting-room-1",
            start_at=_dt("2026-08-07", 14),
            end_at=_dt("2026-08-07", 15),
            title="成员房间占用",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-07", 9),
    )
    assert created.booking.is_active

    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.COMPOSITE,
            target_id="meeting-room-1-2",
            start_at=_dt("2026-08-07", 14),
            end_at=_dt("2026-08-07", 16),
        )
    )

    assert not result.available
    assert ConflictCode.OVERLAPPING_COMPOSITE_BOOKING in result.conflicts


def test_rule_continuous_update_by_match_key_preserves_rule_id() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    first = service.upsert_rule(
        RuleUpsertRequest(
            target_type=TargetType.ROOM,
            target_id="504",
            rule_type=RuleType.MAINTENANCE,
            reason="临时维修",
            actor_id="alice",
            match_key="504:maintenance:2026-08-05",
            time_windows=[RuleTimeWindow(start_at=_dt("2026-08-05", 0), end_at=_dt("2026-08-05", 23, 59))],
        ),
        now=_dt("2026-08-01", 9),
    )
    second = service.upsert_rule(
        RuleUpsertRequest(
            target_type=TargetType.ROOM,
            target_id="504",
            rule_type=RuleType.MAINTENANCE,
            reason="临时维修，只停用下午",
            actor_id="alice",
            match_key="504:maintenance:2026-08-05",
            time_windows=[RuleTimeWindow(start_at=_dt("2026-08-05", 13), end_at=_dt("2026-08-05", 18))],
        ),
        now=_dt("2026-08-01", 10),
    )

    assert second.matched_rule_id == first.rule.id
    assert second.rule.id == first.rule.id
    assert len(second.rule.time_windows) == 1
    assert second.rule.time_windows[0].start_at == _dt("2026-08-05", 13)
    assert second.rule.time_windows[0].end_at == _dt("2026-08-05", 18)
    assert second.state_revision == first.state_revision + 1


def test_protected_rule_cannot_be_modified_by_ordinary_request() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)

    with pytest.raises(ProtectedRuleError):
        service.upsert_rule(
            RuleUpsertRequest(
                target_type=TargetType.ROOM,
                target_id="activity-room",
                rule_type=RuleType.FIXED_UNAVAILABLE,
                reason="改为可预约",
                actor_id="alice",
                match_key="activity-room:fixed_unavailable:lunch",
                time_windows=[],
            ),
            now=_dt("2026-08-01", 9),
        )


def test_cancel_booking_releases_time_window() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="取消测试",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9),
    )
    assert not service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
        )
    ).available

    service.cancel_booking(created.booking.id, reason="会议取消", cancelled_by="alice", now=_dt("2026-08-05", 9, 30))

    result = service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
        )
    )
    assert result.available


def test_list_bookings_active_only_false_includes_cancelled() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="取消列表测试",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9),
    )
    service.cancel_booking(created.booking.id, reason="会议取消", cancelled_by="alice", now=_dt("2026-08-05", 9, 30))

    assert len(service.list_bookings(active_only=True)) == 0
    assert len(service.list_bookings(active_only=False)) == 1
    assert service.list_bookings(active_only=False)[0]["booking"].id == created.booking.id


def test_calendar_expands_recurring_rules() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    events = service.get_calendar_events(
        target_type=TargetType.ROOM,
        target_id="activity-room",
        start_at=_dt("2026-08-04", 0),
        end_at=_dt("2026-08-05", 0),
    )

    assert any(event["start_at"] == _dt("2026-08-04", 12) and event["end_at"] == _dt("2026-08-04", 13) for event in events)


def test_floor_plan_marks_member_room_booked_when_composite_is_booked() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.COMPOSITE,
            target_id="meeting-room-1-2",
            start_at=_dt("2026-08-07", 14),
            end_at=_dt("2026-08-07", 16),
            title="合并会议室",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-07", 9),
    )

    states = service.get_floor_plan_state(at=_dt("2026-08-07", 15))
    meeting_room_1 = next(state for state in states if state["target_id"] == "meeting-room-1")

    assert meeting_room_1["status"] == "booked"


def test_state_revision_monotonic_after_successful_writes() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    first = store.state_revision.current()

    service.upsert_rule(
        RuleUpsertRequest(
            target_type=TargetType.ROOM,
            target_id="504",
            rule_type=RuleType.MAINTENANCE,
            reason="临时维修",
            actor_id="alice",
            match_key="504:maintenance:2026-08-05",
            time_windows=[RuleTimeWindow(start_at=_dt("2026-08-05", 13), end_at=_dt("2026-08-05", 18))],
        ),
        now=_dt("2026-08-01", 9),
    )
    second = store.state_revision.current()
    service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="状态版本测试",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9),
    )
    third = store.state_revision.current()

    assert second == first + 1
    assert third == second + 1


def test_default_small_room_query_excludes_only_505_on_tuesday() -> None:
    store = _store_with_defaults()
    service = MeetingDomainService(store)
    result = service.list_available_targets(
        start_at=_dt("2026-08-04", 10),
        end_at=_dt("2026-08-04", 11),
        room_type="small",
    )

    available = {item["target_id"] for item in result["available"] if item["target_type"] == "room"}
    assert {"503", "504", "506"} <= available
    assert "505" not in available
    assert "502" not in {room.id for room in store.rooms.list()}


def test_sqlite_store_round_trip_for_domain_state() -> None:
    store = _sqlite_store_with_defaults()
    service = MeetingDomainService(store)
    created = service.create_booking(
        BookingCreateRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
            title="SQLite 持久化",
            actor_id="alice",
            organizer_id="alice",
        ),
        now=_dt("2026-08-05", 9),
    )
    revision = service.current_state_revision()

    reopened = SQLiteMeetingDomainStore(store.db)
    reopened_service = MeetingDomainService(reopened)

    assert reopened_service.check_availability(
        AvailabilityRequest(
            target_type=TargetType.ROOM,
            target_id="503",
            start_at=_dt("2026-08-05", 10),
            end_at=_dt("2026-08-05", 11),
        )
    ).available is False
    assert reopened_service.get_calendar_events(
        target_type=TargetType.ROOM,
        target_id="activity-room",
        start_at=_dt("2026-08-04", 0),
        end_at=_dt("2026-08-05", 0),
    )[0]["target_id"] == "activity-room"
    assert reopened_service.current_state_revision() == revision
    assert reopened_service.list_bookings(active_only=True)[0]["booking"].id == created.booking.id

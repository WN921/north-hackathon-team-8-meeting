"""Meeting room rule engine.

RFC-0001: Meeting room domain model and rule engine.
The engine is the single domain decision point for availability, fixed rules,
dynamic rules, booking overlap, and composite-room constraints.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.booking import Booking
from app.domain.common import (
    AvailabilityRequest,
    AvailabilityResult,
    CheckResult,
    CheckType,
    ConflictCode,
    OpeningSchedule,
    RuleType,
    TargetType,
    TimeWindow,
)
from app.domain.rule import RoomRule


class MeetingRuleEngine:
    """Evaluate whether a target can be booked in a candidate time window.

    RFC-0001: The check order is target existence, opening hours, rules,
    composite member availability, and booking overlap.
    """

    def __init__(self, store: object) -> None:
        self.store = store

    def check_availability(self, request: AvailabilityRequest) -> AvailabilityResult:
        """Return a structured availability decision for one target."""

        checks: list[CheckResult] = []
        conflicts: list[ConflictCode] = []
        unavailable_reasons: list[str] = []

        target = self._get_target(request.target_type, request.target_id)
        if target is None:
            return self._unavailable(
                request,
                [self._check(CheckType.TARGET_EXISTS, False, "目标不存在", ConflictCode.TARGET_NOT_FOUND)],
                [ConflictCode.TARGET_NOT_FOUND],
                ["目标不存在"],
            )
        checks.append(self._check(CheckType.TARGET_EXISTS, True, "目标存在"))

        if not self._is_target_active(target):
            return self._unavailable(
                request,
                checks + [self._check(CheckType.TARGET_EXISTS, False, "目标已停用", ConflictCode.TARGET_DISABLED)],
                [ConflictCode.TARGET_DISABLED],
                ["目标已停用"],
            )

        if not self._matches_filters(target, request):
            return self._unavailable(
                request,
                checks + [self._check(CheckType.FILTER, False, "目标不满足筛选条件", ConflictCode.FILTER_MISMATCH)],
                [ConflictCode.FILTER_MISMATCH],
                ["目标不满足筛选条件"],
            )

        if not self._within_opening_hours(request.target_type, request.target_id, request.start_at, request.end_at):
            return self._unavailable(
                request,
                checks + [self._check(CheckType.OPENING_HOURS, False, "不在开放时间内", ConflictCode.OUTSIDE_OPENING_HOURS)],
                [ConflictCode.OUTSIDE_OPENING_HOURS],
                ["不在开放时间内"],
            )
        checks.append(self._check(CheckType.OPENING_HOURS, True, "在开放时间内"))

        if request.target_type == TargetType.COMPOSITE:
            rule_result = self._check_rules(request, checks)
            if rule_result is not None:
                return rule_result
            member_result = self._check_composite_members(request, checks)
            if member_result is not None:
                return member_result
        else:
            rule_result = self._check_rules(request, checks)
            if rule_result is not None:
                return rule_result

        booking_result = self._check_booking_overlap(request, checks)
        if booking_result is not None:
            return booking_result

        return AvailabilityResult.available_result(request, checks)

    def get_target(self, target_type: TargetType, target_id: str) -> object | None:
        """Return a room or composite room by target id."""

        if target_type == TargetType.ROOM:
            return self.store.rooms.get(target_id)
        return self.store.composites.get(target_id)

    def get_target_opening_schedules(self, target_type: TargetType, target_id: str) -> list[OpeningSchedule]:
        """Return opening schedules for a target.

        RFC-0001: Composite rooms inherit the schedules of all member rooms;
        a composite is available only when every member room is open.
        """

        if target_type == TargetType.ROOM:
            return self._opening_schedules_for_room(target_id)
        composite = self.store.composites.get(target_id)
        if composite is None:
            return []
        schedules: list[OpeningSchedule] = []
        for member_id in composite.member_room_ids:
            schedules.extend(self._opening_schedules_for_room(member_id))
        return schedules

    def get_target_rules(self, target_type: TargetType, target_id: str) -> list[RoomRule]:
        """Return rules for a target, including protected fixed rules."""

        return self.store.rules.list_for_target(target_type, target_id, include_protected=True)

    def get_active_bookings(self) -> list[Booking]:
        """Return all active bookings."""

        return self.store.bookings.list_active()

    def _opening_schedules_for_room(self, room_id: str) -> list[OpeningSchedule]:
        repository = getattr(self.store, "opening_schedules", {})
        if hasattr(repository, "list_for_room"):
            return list(repository.list_for_room(room_id))
        return list(repository.get(room_id, []))

    def _check(self, check_type: CheckType, passed: bool, message: str | None = None, conflict_code: ConflictCode | None = None) -> CheckResult:
        return CheckResult(check_type=check_type, passed=passed, message=message, conflict_code=conflict_code)

    def _unavailable(
        self,
        request: AvailabilityRequest,
        checks: list[CheckResult],
        conflicts: list[ConflictCode],
        unavailable_reasons: list[str],
    ) -> AvailabilityResult:
        return AvailabilityResult.unavailable_result(request, checks, conflicts, unavailable_reasons)

    def _get_target(self, target_type: TargetType, target_id: str) -> object | None:
        if target_type == TargetType.ROOM:
            return self.store.rooms.get(target_id)
        return self.store.composites.get(target_id)

    def _is_target_active(self, target: object) -> bool:
        return bool(getattr(target, "active", True))

    def _matches_filters(self, target: object, request: AvailabilityRequest) -> bool:
        if request.room_type is not None and getattr(target, "type", None) != request.room_type:
            return False
        if request.capacity is not None and int(getattr(target, "capacity", 0)) < request.capacity:
            return False
        equipment = list(request.equipment)
        if equipment and not target.has_equipment(equipment):
            return False
        return True

    def _within_opening_hours(self, target_type: TargetType, target_id: str, start_at: datetime, end_at: datetime) -> bool:
        schedules = self.get_target_opening_schedules(target_type, target_id)
        if not schedules:
            return False
        if target_type == TargetType.ROOM:
            return any(schedule.contains(start_at, end_at) for schedule in schedules)
        composite = self.store.composites.get(target_id)
        if composite is None:
            return False
        for member_id in composite.member_room_ids:
            member_schedules = [schedule for schedule in schedules if schedule.room_id == member_id]
            if not any(schedule.contains(start_at, end_at) for schedule in member_schedules):
                return False
        return True

    def _check_rules(self, request: AvailabilityRequest, checks: list[CheckResult]) -> AvailabilityResult | None:
        for rule in self.get_target_rules(request.target_type, request.target_id):
            if rule.matches(request.start_at, request.end_at):
                conflict_code = self._conflict_code_for_rule(rule.rule_type)
                return self._unavailable(
                    request,
                    checks + [self._check(CheckType.ROOM_RULE, False, rule.reason, conflict_code)],
                    [conflict_code],
                    [rule.reason],
                )
        checks.append(self._check(CheckType.ROOM_RULE, True, "未命中不可预约规则"))
        return None

    def _check_composite_members(self, request: AvailabilityRequest, checks: list[CheckResult]) -> AvailabilityResult | None:
        composite = self.store.composites.get(request.target_id)
        if composite is None:
            return self._unavailable(
                request,
                checks + [self._check(CheckType.COMPOSITE_MEMBER, False, "组合空间不存在", ConflictCode.TARGET_NOT_FOUND)],
                [ConflictCode.TARGET_NOT_FOUND],
                ["组合空间不存在"],
            )
        for member_id in composite.member_room_ids:
            member_request = AvailabilityRequest(
                target_type=TargetType.ROOM,
                target_id=member_id,
                start_at=request.start_at,
                end_at=request.end_at,
                capacity=request.capacity,
                equipment=request.equipment,
                room_type=request.room_type,
                allow_composite=request.allow_composite,
            )
            member_result = self.check_availability(member_request)
            if not member_result.available:
                conflicts = [
                    ConflictCode.OVERLAPPING_COMPOSITE_BOOKING if conflict == ConflictCode.OVERLAPPING_BOOKING else conflict
                    for conflict in member_result.conflicts
                ]
                return self._unavailable(
                    request,
                    checks + [self._check(CheckType.COMPOSITE_MEMBER, False, "; ".join(member_result.unavailable_reasons) or "成员房间不可用", conflicts[0] if conflicts else ConflictCode.MEMBER_ROOM_UNAVAILABLE)],
                    conflicts or [ConflictCode.MEMBER_ROOM_UNAVAILABLE],
                    member_result.unavailable_reasons,
                )
        checks.append(self._check(CheckType.COMPOSITE_MEMBER, True, "成员房间可用"))
        return None

    def _check_booking_overlap(self, request: AvailabilityRequest, checks: list[CheckResult]) -> AvailabilityResult | None:
        candidate = TimeWindow(request.start_at, request.end_at)
        for booking in self.get_active_bookings():
            if request.ignore_booking_id and booking.id == request.ignore_booking_id:
                continue
            booking_windows = self._booking_windows(booking.id)
            for window in booking_windows:
                if not candidate.overlaps(window):
                    continue
                if self._booking_touches_request_target(booking, request):
                    conflict_code = self._conflict_code_for_booking(booking, request)
                    return self._unavailable(
                        request,
                        checks + [self._check(CheckType.BOOKING_OVERLAP, False, "与已有预约冲突", conflict_code)],
                        [conflict_code],
                        ["与已有预约冲突"],
                    )
        checks.append(self._check(CheckType.BOOKING_OVERLAP, True, "无预约重叠"))
        return None

    def _booking_windows(self, booking_id: str) -> list[TimeWindow]:
        repository = getattr(self.store, "booking_windows", {})
        if hasattr(repository, "list_for_booking"):
            windows = repository.list_for_booking(booking_id)
        else:
            windows = repository.get(booking_id, [])
        return [window for window in windows if isinstance(window, TimeWindow)]

    def _booking_touches_request_target(self, booking: Booking, request: AvailabilityRequest) -> bool:
        if request.target_type == TargetType.ROOM:
            return booking.target_id == request.target_id or (
                booking.target_type == TargetType.COMPOSITE
                and self._composite_contains_room(booking.target_id, request.target_id)
            )
        if request.target_type == TargetType.COMPOSITE:
            composite = self.store.composites.get(request.target_id)
            if composite is None:
                return False
            if booking.target_type == TargetType.ROOM:
                return booking.target_id in composite.member_room_ids
            return booking.target_id != request.target_id and bool(set(composite.member_room_ids) & set(self._composite_member_ids(booking.target_id)))
        return False

    def _conflict_code_for_rule(self, rule_type: RuleType) -> ConflictCode:
        return {
            RuleType.FIXED_UNAVAILABLE: ConflictCode.FIXED_UNAVAILABLE,
            RuleType.WEEKLY_UNAVAILABLE: ConflictCode.WEEKLY_UNAVAILABLE,
            RuleType.TEMPORARY_UNAVAILABLE: ConflictCode.TEMPORARY_UNAVAILABLE,
            RuleType.MAINTENANCE: ConflictCode.MAINTENANCE,
            RuleType.ACTIVITY_BLOCK: ConflictCode.ACTIVITY_BLOCK,
        }.get(rule_type, ConflictCode.FIXED_UNAVAILABLE)

    def _conflict_code_for_booking(self, booking: Booking, request: AvailabilityRequest) -> ConflictCode:
        if request.target_type == TargetType.COMPOSITE:
            return ConflictCode.OVERLAPPING_COMPOSITE_BOOKING
        if booking.target_type == TargetType.COMPOSITE or request.target_type == TargetType.COMPOSITE:
            return ConflictCode.OVERLAPPING_COMPOSITE_BOOKING
        return ConflictCode.OVERLAPPING_BOOKING

    def _composite_contains_room(self, composite_id: str, room_id: str) -> bool:
        return room_id in self._composite_member_ids(composite_id)

    def _composite_member_ids(self, composite_id: str) -> list[str]:
        composite = self.store.composites.get(composite_id)
        return list(composite.member_room_ids) if composite else []

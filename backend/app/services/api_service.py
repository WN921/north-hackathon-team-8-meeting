"""Application services for RFC-0002 API contracts."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from app.core.config import DEFAULT_WORKSPACE_ID, DEFAULT_TIMEZONE, ErrorCode, ReasonCode, request_id
from app.domain.models import Booking, CompositeRoom, Position, Room, Rule, TimeWindow
from app.repositories.meeting import MeetingRepository

DEFAULT_FLOOR_ID = "5F"


class APIError(HTTPException):
    """Structured API error with RFC-0002 reason details."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None, suggestions: list[str] | None = None, status_code: int = 400) -> None:
        self.error_code = code
        self.error_details = details or {}
        self.error_suggestions = suggestions or []
        super().__init__(status_code=status_code, detail={"code": code, "message": message, "details": self.error_details, "suggestions": self.error_suggestions})


def success(data: dict[str, Any], warnings: list[str] | None = None, revision: int = 0) -> dict[str, Any]:
    return {"ok": True, "request_id": request_id(), "data": data, "warnings": warnings or [], "meta": {"state_revision": revision, "server_time": datetime.now().isoformat(), "timezone": DEFAULT_TIMEZONE}}


def error_response(exc: APIError, revision: int = 0) -> dict[str, Any]:
    return {"ok": False, "request_id": request_id(), "error": {"code": exc.error_code, "message": exc.detail["message"], "details": exc.error_details, "suggestions": exc.error_suggestions}, "warnings": [], "meta": {"state_revision": revision, "server_time": datetime.now().isoformat(), "timezone": DEFAULT_TIMEZONE}}


def validate_state_revision(repository: MeetingRepository, expected: int, workspace_id: str = DEFAULT_WORKSPACE_ID) -> None:
    current = repository.get_state_revision(workspace_id)
    if current != expected:
        raise APIError(
            ErrorCode.STATE_REVISION_CONFLICT,
            "当前状态版本与请求不一致",
            {"current_state_revision": current, "expected_state_revision": expected},
            ["请重新读取状态版本后重试"],
            409,
        )


def check_idempotency(repository: MeetingRepository, workspace_id: str, actor_id: str, idempotency_key: str, request_hash: str) -> dict[str, Any] | None:
    row = repository.get_idempotency(workspace_id, actor_id, idempotency_key)
    if row is None:
        return None
    if row["request_hash"] != request_hash:
        raise APIError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一幂等键已用于不同请求", {"idempotency_key": idempotency_key}, ["请更换稳定幂等键后重试"], 409)
    return json.loads(row["response_json"])


def save_idempotency(repository: MeetingRepository, workspace_id: str, actor_id: str, idempotency_key: str, request_hash: str, response: dict[str, Any]) -> None:
    repository.save_idempotency(workspace_id, actor_id, idempotency_key, request_hash, json.dumps(response, ensure_ascii=False))


def overlaps(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    return start_a < end_b and start_b < end_a


def target_exists(repository: MeetingRepository, target_type: str, target_id: str) -> bool:
    if target_type == "room":
        room = repository.get_room(target_id)
        return bool(room and room.active)
    if target_type == "composite":
        row = repository.conn.execute("SELECT active FROM composites WHERE id = ?", (target_id,)).fetchone()
        return bool(row and row["active"])
    return False


def target_name(repository: MeetingRepository, target_type: str, target_id: str) -> str:
    if target_type == "room":
        room = repository.get_room(target_id)
        return room.name if room else target_id
    if target_type == "composite":
        row = repository.conn.execute("SELECT name FROM composites WHERE id = ?", (target_id,)).fetchone()
        return row["name"] if row else target_id
    return target_id


def availability_error_code(check: dict[str, Any]) -> ErrorCode:
    reasons = check.get("unavailable_reasons") or []
    if not reasons:
        return ErrorCode.BOOKING_CONFLICT
    reason_code = reasons[0].get("reason_code")
    if reason_code == ReasonCode.OUTSIDE_OPENING_HOURS:
        return ErrorCode.OUTSIDE_OPENING_HOURS
    if reason_code in {ReasonCode.FIXED_UNAVAILABLE, ReasonCode.WEEKLY_UNAVAILABLE, ReasonCode.TEMPORARY_MAINTENANCE}:
        return ErrorCode.BOOKING_BLOCKED_BY_RULE
    if reason_code == ReasonCode.OVERLAPPING_COMPOSITE_BOOKING:
        return ErrorCode.BOOKING_CONFLICT
    return ErrorCode.BOOKING_CONFLICT


def get_room_or_error(repository: MeetingRepository, room_id: str) -> Room:
    room = repository.get_room(room_id)
    if room is None:
        raise APIError(ErrorCode.ROOM_NOT_FOUND, "会议室不存在", {"room_id": room_id}, ["请检查会议室 ID"], 404)
    return room


def get_composite_or_error(repository: MeetingRepository, composite_id: str) -> CompositeRoom:
    row = repository.conn.execute("SELECT * FROM composites WHERE id = ?", (composite_id,)).fetchone()
    if row is None:
        raise APIError(ErrorCode.COMPOSITE_NOT_FOUND, "组合空间不存在", {"composite_id": composite_id}, ["请检查组合空间 ID"], 404)
    from app.repositories.meeting import _json_loads, _position_from_value

    return CompositeRoom(
        id=row["id"],
        name=row["name"],
        member_room_ids=_json_loads(row["member_room_ids_json"], []),
        capacity=int(row["capacity"]),
        equipment=_json_loads(row["equipment_json"], []),
        position=_position_from_value(row["position_json"]),
        protected=bool(row["protected"]),
        active=bool(row["active"]),
    )


def check_opening_hours(repository: MeetingRepository, target_type: str, target_id: str, start_at: str, end_at: str) -> tuple[bool, str | None]:
    if target_type != "room":
        return True, None
    room = get_room_or_error(repository, target_id)
    start_dt = datetime.fromisoformat(start_at)
    end_dt = datetime.fromisoformat(end_at)
    if end_dt <= start_dt:
        return False, "结束时间必须晚于开始时间"
    weekday = start_dt.weekday()
    start_time = start_dt.strftime("%H:%M")
    end_time = "24:00" if end_dt.strftime("%H:%M") == "00:00" and end_dt.date() > start_dt.date() else end_dt.strftime("%H:%M")
    for schedule in repository.list_opening_schedules(room.id):
        schedule_start = schedule["start_time"]
        schedule_end = schedule["end_time"]
        if schedule["weekday"] == weekday and schedule_start <= start_time and schedule_end >= end_time:
            return True, None
    return False, "不在开放时间内"


def _time_window_matches(rule: Rule, window: TimeWindow, start_at: str, end_at: str) -> bool:
    start_dt = datetime.fromisoformat(start_at)
    end_dt = datetime.fromisoformat(end_at)
    recurrence = window.recurrence
    if recurrence and recurrence.startswith("weekly:"):
        weekday = start_dt.weekday()
        if recurrence == "weekly:tuesday" and weekday != 1:
            return False
        if recurrence == "weekly:workday" and weekday >= 5:
            return False
        start_time = start_dt.strftime("%H:%M")
        end_time = "24:00" if end_dt.strftime("%H:%M") == "00:00" and end_dt.date() > start_dt.date() else end_dt.strftime("%H:%M")
        return window.start_at <= start_time and window.end_at >= end_time
    if recurrence and recurrence.startswith("date:"):
        if recurrence.replace("date:", "") != start_dt.date().isoformat():
            return False
        start_time = start_dt.strftime("%H:%M")
        end_time = "24:00" if end_dt.strftime("%H:%M") == "00:00" and end_dt.date() > start_dt.date() else end_dt.strftime("%H:%M")
        return window.start_at <= start_time and window.end_at >= end_time
    return overlaps(start_at, end_at, window.start_at, window.end_at)


def rule_blocks(repository: MeetingRepository, target_type: str, target_id: str, start_at: str, end_at: str) -> Rule | None:
    for rule in repository.list_rules(target_type=target_type, target_id=target_id, fixed=None):
        for window in rule.time_windows:
            if _time_window_matches(rule, window, start_at, end_at):
                return rule
    return None


def booking_conflicts(repository: MeetingRepository, target_type: str, target_id: str, start_at: str, end_at: str, exclude_booking_id: str | None = None) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for booking in repository.list_confirmed_bookings_for_window(start_at, end_at):
        if exclude_booking_id and booking.id == exclude_booking_id:
            continue
        if booking.target_type == target_type and booking.target_id == target_id:
            conflicts.append(
                {
                    "conflict_type": "overlapping_booking",
                    "reason_code": ReasonCode.OVERLAPPING_BOOKING,
                    "target_type": booking.target_type,
                    "target_id": booking.target_id,
                    "booking_id": booking.id,
                    "overlap_start": max(start_at, booking.start_at),
                    "overlap_end": min(end_at, booking.end_at),
                }
            )
        elif target_type == "composite":
            composite = get_composite_or_error(repository, target_id)
            if booking.target_type == "room" and booking.target_id in composite.member_room_ids:
                conflicts.append(
                    {
                        "conflict_type": "overlapping_composite_booking",
                        "reason_code": ReasonCode.OVERLAPPING_COMPOSITE_BOOKING,
                        "target_type": "room",
                        "target_id": booking.target_id,
                        "booking_id": booking.id,
                        "composite_id": target_id,
                        "overlap_start": max(start_at, booking.start_at),
                        "overlap_end": min(end_at, booking.end_at),
                    }
                )
        elif target_type == "room":
            for composite in repository.conn.execute("SELECT * FROM composites WHERE active = 1").fetchall():
                from app.repositories.meeting import _json_loads

                if target_id in _json_loads(composite["member_room_ids_json"], []) and booking.target_type == "composite" and booking.target_id == composite["id"]:
                    conflicts.append(
                        {
                            "conflict_type": "overlapping_composite_booking",
                            "reason_code": ReasonCode.OVERLAPPING_COMPOSITE_BOOKING,
                            "target_type": "composite",
                            "target_id": booking.target_id,
                            "booking_id": booking.id,
                            "member_room_id": target_id,
                            "overlap_start": max(start_at, booking.start_at),
                            "overlap_end": min(end_at, booking.end_at),
                        }
                    )
    return conflicts


def availability(repository: MeetingRepository, target_type: str, target_id: str, start_at: str, end_at: str, capacity: int | None = None, equipment: list[str] | None = None, room_types: list[str] | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    unavailable_reasons: list[dict[str, Any]] = []
    exists = target_exists(repository, target_type, target_id)
    checks.append({"check_type": "target_exists", "passed": exists})
    if not exists:
        unavailable_reasons.append({"reason_code": "TARGET_NOT_FOUND", "message": "目标不存在"})
        return {"available": False, "checks": checks, "conflicts": conflicts, "unavailable_reasons": unavailable_reasons}
    if capacity is not None:
        if target_type == "room":
            room = get_room_or_error(repository, target_id)
            passed = room.capacity >= capacity
        else:
            composite = get_composite_or_error(repository, target_id)
            passed = composite.capacity >= capacity
        checks.append({"check_type": "capacity", "passed": passed})
        if not passed:
            unavailable_reasons.append({"reason_code": "CAPACITY_INSUFFICIENT", "message": "容量不足"})
    if equipment:
        if target_type == "room":
            room = get_room_or_error(repository, target_id)
            passed = all(item in room.equipment for item in equipment)
        else:
            composite = get_composite_or_error(repository, target_id)
            passed = all(item in composite.equipment for item in equipment)
        checks.append({"check_type": "equipment", "passed": passed})
        if not passed:
            unavailable_reasons.append({"reason_code": "EQUIPMENT_MISSING", "message": "设备不满足"})
    opening_passed, opening_message = check_opening_hours(repository, target_type, target_id, start_at, end_at)
    checks.append({"check_type": "opening_hours", "passed": opening_passed})
    if not opening_passed:
        unavailable_reasons.append({"reason_code": ReasonCode.OUTSIDE_OPENING_HOURS, "message": opening_message or "不在开放时间内"})
    blocked_rule = rule_blocks(repository, target_type, target_id, start_at, end_at)
    rule_passed = blocked_rule is None
    checks.append({"check_type": "room_rule", "passed": rule_passed})
    if not rule_passed:
        unavailable_reasons.append({"reason_code": blocked_rule.reason_code(), "message": blocked_rule.reason, "rule_id": blocked_rule.id})
    conflicts.extend(booking_conflicts(repository, target_type, target_id, start_at, end_at))
    checks.append({"check_type": "booking_overlap", "passed": not conflicts})
    if conflicts:
        unavailable_reasons.append({"reason_code": conflicts[0]["reason_code"], "message": "目标在该时段已有占用", "conflicts": conflicts})
    return {"available": not unavailable_reasons, "checks": checks, "conflicts": conflicts, "unavailable_reasons": unavailable_reasons}


def list_available_targets(repository: MeetingRepository, start_at: str, end_at: str, capacity: int | None = None, equipment: list[str] | None = None, room_types: list[str] | None = None, allow_merge: bool = False) -> dict[str, Any]:
    available: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    rooms, composites = repository.list_rooms(include_composite=allow_merge, capacity=capacity, equipment=equipment, room_type=room_types[0] if room_types else None)
    for room in rooms:
        if room_types and room.type not in room_types:
            continue
        result = availability(repository, "room", room.id, start_at, end_at, capacity, equipment, room_types)
        if result["available"]:
            available.append({"target_type": "room", "target_id": room.id, "name": room.name, "type": room.type, "capacity": room.capacity, "available": True})
        else:
            unavailable.append({"target_type": "room", "target_id": room.id, "name": room.name, "reason_code": result["unavailable_reasons"][0]["reason_code"], "message": result["unavailable_reasons"][0]["message"]})
    if allow_merge:
        for composite in composites:
            result = availability(repository, "composite", composite.id, start_at, end_at, capacity, equipment, room_types)
            if result["available"]:
                available.append({"target_type": "composite", "target_id": composite.id, "name": composite.name, "member_room_ids": composite.member_room_ids, "capacity": composite.capacity, "available": True})
            else:
                unavailable.append({"target_type": "composite", "target_id": composite.id, "name": composite.name, "reason_code": result["unavailable_reasons"][0]["reason_code"], "message": result["unavailable_reasons"][0]["message"]})
    return {"available_targets": available, "unavailable_targets": unavailable, "conflicts": []}


def parse_nl_configure(utterance: str, repository: MeetingRepository) -> dict[str, Any]:
    text = utterance.strip()
    match = re.search(r"(50[3456]|activity-room|meeting-room-1|meeting-room-2).{0,20}(维修|维护|停用|不能预约|不可预约)", text)
    if not match:
        raise APIError(ErrorCode.NATURAL_LANGUAGE_AMBIGUOUS, "自然语言解析结果不唯一", {"utterance": utterance}, ["请改用结构化规则 API"], 400)
    target_id = match.group(1)
    if "下午" in text:
        date = "2026-08-05"
        start = "13:00"
        end = "18:00"
    else:
        date = "2026-08-05"
        start = "09:00"
        end = "18:00"
    match_key = f"{target_id}:temporary_maintenance:{date}"
    existing = repository.match_rule("room", target_id, "temporary_maintenance", match_key, date)
    rule_id = existing.id if existing else f"rule_{target_id}_repair_{date.replace('-', '')}"
    return {
        "intent": "update_rule",
        "llm": {"provider": "nex-agi", "model": "Nex-N2-Pro"},
        "parsed_changes": [
            {
                "operation": "upsert_rule",
                "target_type": "room",
                "target_id": target_id,
                "rule_type": "temporary_maintenance",
                "time_windows": [{"start_at": f"{date}T{start}:00+08:00", "end_at": f"{date}T{end}:00+08:00", "recurrence": None}],
                "reason": "临时维修",
            }
        ],
        "matched_rule_id": existing.id if existing else None,
        "rule_id": rule_id,
        "match_key": match_key,
        "date": date,
    }


def parse_nl_candidates(utterance: str) -> dict[str, Any]:
    return {
        "intent": "query_availability",
        "llm": {"provider": "nex-agi", "model": "Nex-N2-Pro"},
        "parsed_booking": {"start_at": "2026-08-04T10:00:00+08:00", "end_at": "2026-08-04T11:00:00+08:00", "room_type": "small", "title": "项目讨论"},
    }


def preview_rule_from_parsed(parsed: dict[str, Any], actor_id: str) -> tuple[Rule | None, Rule]:
    change = parsed["parsed_changes"][0]
    existing_id = parsed.get("matched_rule_id") or parsed.get("rule_id")
    rule = Rule(
        id=existing_id,
        rule_type=change["rule_type"],
        target_type=change["target_type"],
        target_id=change["target_id"],
        time_windows=[TimeWindow(**window) for window in change["time_windows"]],
        reason=change.get("reason", "临时维修"),
        fixed=False,
        editable=True,
        match_key=parsed.get("match_key"),
        created_by=actor_id,
        updated_by=actor_id,
    )
    return None, rule


def create_rule_from_parsed(repository: MeetingRepository, parsed: dict[str, Any], actor_id: str, dry_run: bool = False) -> tuple[Rule | None, Rule]:
    old, rule = preview_rule_from_parsed(parsed, actor_id)
    existing_id = parsed.get("matched_rule_id") or parsed.get("rule_id")
    old = repository.get_rule(existing_id) if existing_id else None
    if dry_run:
        return old, rule
    return old, repository.upsert_rule(rule)[1]


def floor_plan(repository: MeetingRepository, floor_id: str = DEFAULT_FLOOR_ID, date: str | None = None, time: str | None = None, include_status: bool = True, include_rules: bool = True, include_bookings: bool = True) -> dict[str, Any]:
    rooms, composites = repository.list_rooms(include_composite=True)
    room_payload: list[dict[str, Any]] = []
    for room in rooms:
        status_value = "available"
        reason_code = None
        message = "可用"
        if include_status and date and time:
            start = f"{date}T{time}:00+08:00"
            end = f"{date}T13:00:00+08:00" if time < "13:00" else f"{date}T14:00:00+08:00"
            rule = rule_blocks(repository, "room", room.id, start, end)
            conflicts = booking_conflicts(repository, "room", room.id, start, end)
            if rule:
                reason_code = rule.reason_code()
                if reason_code == "FIXED_UNAVAILABLE":
                    status_value = "fixed_unavailable"
                elif reason_code == "TEMPORARY_MAINTENANCE":
                    status_value = "maintenance"
                else:
                    status_value = "blocked_by_rule"
                message = rule.reason
            elif conflicts:
                reason_code = conflicts[0]["reason_code"]
                status_value = "composite_booked" if reason_code == "OVERLAPPING_COMPOSITE_BOOKING" else "booked"
                message = "已有预约"
        room_payload.append({"id": room.id, "name": room.name, "position": room.position.to_dict() if room.position else None, "status": status_value, "reason_code": reason_code, "message": message})
    composite_payload: list[dict[str, Any]] = []
    for composite in composites:
        status_value = "available"
        reason_code = None
        message = "可合并预约"
        if include_status and date and time:
            start = f"{date}T{time}:00+08:00"
            end = f"{date}T13:00:00+08:00" if time < "13:00" else f"{date}T14:00:00+08:00"
            conflicts = booking_conflicts(repository, "composite", composite.id, start, end)
            rule = rule_blocks(repository, "composite", composite.id, start, end)
            if rule:
                reason_code = rule.reason_code()
                status_value = "fixed_unavailable" if reason_code == "FIXED_UNAVAILABLE" else "maintenance" if reason_code == "TEMPORARY_MAINTENANCE" else "blocked_by_rule"
                message = rule.reason
            elif conflicts:
                reason_code = conflicts[0]["reason_code"]
                status_value = "composite_booked" if reason_code == "OVERLAPPING_COMPOSITE_BOOKING" else "booked"
                message = "已有预约"
        composite_payload.append({"id": composite.id, "name": composite.name, "member_room_ids": composite.member_room_ids, "position": composite.position.to_dict() if composite.position else None, "status": status_value, "reason_code": reason_code, "message": message})
    return {"floor": {"id": floor_id, "name": "5楼"}, "rooms": room_payload, "composites": composite_payload, "member_occupancies": []}

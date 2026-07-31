#!/usr/bin/env python3
"""RFC-based smoke test for the local meeting-room system.

The script validates the RFC-0001/0002/0003/0004 contract that can be checked
without mutating persistent production state by default. It exercises the
FastAPI boundary and the NAC meeting-agent artifact shape; it does not call NAC
Gateway directly. Use acceptance/scripts/nac_gateway_smoke.sh for AK:SK gateway
connectivity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error, parse, request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_USERNAME = "demo"
DEFAULT_PASSWORD = "demo-password"
DEFAULT_WORKSPACE_ID = "default"
DEFAULT_ACTOR_ID = "demo-user"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_TEST_PREFIX = "rfc-smoke"
SHANGHAI = timezone(timedelta(hours=8))
UTC = timezone.utc


@dataclass(frozen=True)
class ApiClient:
    base_url: str
    token: str
    workspace_id: str
    actor_id: str
    timeout: float = 20.0

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, expected: set[int] | None = None) -> dict[str, Any]:
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.url(path),
            data=data,
            method=method.upper(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310 - local smoke test.
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if expected is None or exc.code not in expected:
                raise AssertionError(f"HTTP {exc.code} for {method} {path}: {raw}") from exc
            return json.loads(raw) if raw else {}

    def write_body(self, payload: dict[str, Any], *, operation: str, dry_run: bool = False, revision: int | None = None) -> dict[str, Any]:
        body = dict(payload)
        body.setdefault("workspace_id", self.workspace_id)
        body.setdefault("actor_id", self.actor_id)
        body.setdefault("expected_state_revision", revision)
        body.setdefault("idempotency_key", self.idempotency_key(operation, body))
        body.setdefault("dry_run", dry_run)
        return body

    def idempotency_key(self, operation: str, body: dict[str, Any]) -> str:
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        return f"{DEFAULT_TEST_PREFIX}:{self.workspace_id}:{self.actor_id}:{operation}:{digest}"


class Runner:
    def __init__(self, client: ApiClient, dry_run: bool, timezone_name: str, allow_writes: bool) -> None:
        self.client = client
        self.dry_run = dry_run
        self.timezone_name = timezone_name
        self.allow_writes = allow_writes
        self.results: list[dict[str, Any]] = []
        self.revision = 0

    def record(self, name: str, *, ok: bool, details: dict[str, Any] | None = None) -> None:
        self.results.append({"name": name, "ok": ok, "details": details or {}})

    def run(self) -> int:
        self.check_health()
        self.check_openapi()
        self.check_rooms_and_rules()
        self.check_tuesday_small_rooms()
        self.check_lunch_block()
        self.check_composite_block()
        self.check_booking_cancel_release()
        self.check_nl_contract()
        self.check_calendar_floor_plan()
        self.check_agent_artifact_contract()
        return self.print_report()

    def check_health(self) -> None:
        payload = self.client.request("GET", "/api/health")
        self.remember_revision(payload)
        self.record("health", ok=payload.get("ok") is True, details={"revision": self.revision, "warnings": payload.get("warnings", [])})

    def check_openapi(self) -> None:
        payload = self.client.request("GET", "/openapi.json", expected={200})
        paths = payload.get("paths") if isinstance(payload, dict) else {}
        required = {
            "/api/availability:query",
            "/api/availability:check",
            "/api/nl/configure",
            "/api/nl/bookings:candidates",
            "/api/bookings",
            "/api/bookings/{booking_id}/cancel",
            "/api/calendar",
            "/api/floor-plan",
        }
        missing = sorted(required - set(paths or {}))
        self.record("openapi_contracts", ok=not missing, details={"missing_paths": missing})

    def check_rooms_and_rules(self) -> None:
        rooms = self.client.request("GET", "/api/rooms?include_composite=true")
        room_ids = {item["id"] for item in rooms.get("data", {}).get("rooms", [])}
        composite_ids = {item["id"] for item in rooms.get("data", {}).get("composites", [])}
        rules = self.client.request("GET", "/api/rules?fixed=true")
        rule_ids = {item.get("rule_id") or item.get("id") for item in rules.get("data", {}).get("items", [])}
        expected_rooms = {"activity-room", "meeting-room-1", "meeting-room-2", "503", "504", "505", "506"}
        expected_rules = {"rule_lunch_activity_room", "rule_505_tuesday"}
        self.record(
            "default_rooms_rules",
            ok=expected_rooms <= room_ids and "meeting-room-1-2" in composite_ids and expected_rules <= rule_ids,
            details={"rooms": sorted(room_ids), "composites": sorted(composite_ids), "rules": sorted(rule_ids)},
        )
        self.revision = max(self.revision, self.meta_revision(rooms), self.meta_revision(rules))

    def check_tuesday_small_rooms(self) -> None:
        start_at, end_at = next_tuesday_window()
        payload = self.client.request(
            "POST",
            "/api/availability:query",
            body={"start_at": start_at, "end_at": end_at, "room_types": ["small"], "allow_merge": False, "timezone": self.timezone_name},
        )
        available = {item["target_id"] for item in payload.get("data", {}).get("available_targets", [])}
        unavailable = {item["target_id"]: item.get("reason_code") for item in payload.get("data", {}).get("unavailable_targets", [])}
        ok = {"503", "506"} <= available and unavailable.get("505") in {"WEEKLY_UNAVAILABLE", "FIXED_UNAVAILABLE"}
        self.record("tuesday_small_rooms", ok=ok, details={"start_at": start_at, "available": sorted(available), "unavailable": unavailable})
        self.remember_revision(payload)

    def check_lunch_block(self) -> None:
        start_at, end_at = next_workday_lunch_window()
        payload = self.client.request(
            "POST",
            "/api/availability:check",
            body={"target_type": "room", "target_id": "activity-room", "start_at": start_at, "end_at": end_at},
            expected={409},
        )
        reasons = payload.get("data", {}).get("unavailable_reasons", [])
        reasons.extend(payload.get("error", {}).get("details", {}).get("unavailable_reasons", []))
        reason_codes = {item.get("reason_code") for item in reasons}
        reason_codes.update(item.get("reason_code") for conflict in reasons for item in conflict.get("conflicts", []))
        available = payload.get("data", {}).get("available", payload.get("error", {}).get("details", {}).get("available"))
        ok = available is False and "FIXED_UNAVAILABLE" in reason_codes
        self.record("activity_lunch_block", ok=ok, details={"start_at": start_at, "reason_codes": sorted(reason_codes)})
        self.remember_revision(payload)

    def check_composite_block(self) -> None:
        start_at = None
        end_at = None
        checked_windows: list[dict[str, str]] = []
        for offset_days in range(0, 20):
            start_at, end_at = next_wednesday_window(offset_days)
            checked_windows.append({"start_at": start_at, "end_at": end_at})
            composite_payload = self.client.request(
                "POST",
                "/api/availability:check",
                body={"target_type": "composite", "target_id": "meeting-room-1-2", "start_at": start_at, "end_at": end_at},
                expected={200, 409},
            )
            if composite_payload.get("data", {}).get("available") is True:
                break
        else:
            self.record("composite_block", ok=False, details={"reason": "composite is not available in the scanned fixture windows", "checked_windows": checked_windows})
            return
        if not self.allow_writes:
            booking = self.client.request(
                "POST",
                "/api/bookings",
                body=self.client.write_body(
                    {
                        "target_type": "composite",
                        "target_id": "meeting-room-1-2",
                        "start_at": start_at,
                        "end_at": end_at,
                        "title": "RFC smoke composite booking",
                        "organizer_id": self.client.actor_id,
                        "attendees": [self.client.actor_id],
                        "description": "created by RFC contract smoke test",
                    },
                    operation="composite-booking",
                    dry_run=True,
                    revision=self.revision,
                ),
                expected={200, 409},
            )
            self.record(
                "composite_member_block",
                ok=booking.get("ok") is True or booking.get("error", {}).get("code") in {"STATE_REVISION_CONFLICT", "IDEMPOTENCY_KEY_REUSED"},
                details={"dry_run_only": True, "booking_id": booking.get("data", {}).get("booking_id"), "warnings": booking.get("warnings", []), "error": booking.get("error")},
            )
            self.remember_revision(booking)
            return
        booking = self.client.request(
            "POST",
            "/api/bookings",
            body=self.client.write_body(
                {
                    "target_type": "composite",
                    "target_id": "meeting-room-1-2",
                    "start_at": start_at,
                    "end_at": end_at,
                    "title": "RFC smoke composite booking",
                    "organizer_id": self.client.actor_id,
                    "attendees": [self.client.actor_id],
                    "description": "created by RFC contract smoke test",
                },
                operation="composite-booking",
                dry_run=False,
                revision=self.revision,
            ),
        )
        booking_id = booking.get("data", {}).get("booking_id") if booking.get("ok") else None
        member_payload = self.client.request(
            "POST",
            "/api/availability:check",
            body={"target_type": "room", "target_id": "meeting-room-1", "start_at": start_at, "end_at": end_at},
            expected={200, 409},
        )
        reason_codes = {item.get("reason_code") for item in member_payload.get("data", {}).get("unavailable_reasons", [])}
        ok = bool(booking_id) and "OVERLAPPING_COMPOSITE_BOOKING" in reason_codes
        self.record("composite_member_block", ok=ok, details={"booking_id": booking_id, "reason_codes": sorted(reason_codes)})
        self.revision = self.meta_revision(booking)

    def check_booking_cancel_release(self) -> None:
        start_at = None
        end_at = None
        checked_windows: list[dict[str, str]] = []
        for offset_days in range(0, 10):
            start_at, end_at = next_thursday_window(offset_days)
            checked_windows.append({"start_at": start_at, "end_at": end_at})
            availability = self.client.request(
                "POST",
                "/api/availability:check",
                body={"target_type": "room", "target_id": "503", "start_at": start_at, "end_at": end_at},
                expected={200, 409},
            )
            if availability.get("data", {}).get("available") is True:
                break
        else:
            self.record("booking_cancel_release", ok=False, details={"reason": "503 is not available in the scanned fixture windows", "checked_windows": checked_windows})
            return
        create_payload = self.client.request(
            "POST",
            "/api/bookings",
            body=self.client.write_body(
                {
                    "target_type": "room",
                    "target_id": "503",
                    "start_at": start_at,
                    "end_at": end_at,
                    "title": "RFC smoke booking",
                    "organizer_id": self.client.actor_id,
                    "attendees": [self.client.actor_id],
                    "description": "created by RFC contract smoke test",
                },
                operation="booking-cancel-release",
                dry_run=not self.allow_writes,
                revision=self.revision,
            ),
            expected={200, 409},
        )
        booking_id = create_payload.get("data", {}).get("booking_id") if create_payload.get("ok") else None
        if not self.allow_writes:
            self.record("booking_cancel_release", ok=create_payload.get("ok") is True, details={"dry_run_only": True, "booking_id": booking_id, "warnings": create_payload.get("warnings", []), "error": create_payload.get("error")})
            self.remember_revision(create_payload)
            return
        if not booking_id:
            self.record("booking_cancel_release", ok=False, details={"create_error": create_payload.get("error")})
            return
        cancel_payload = self.client.request(
            "POST",
            f"/api/bookings/{booking_id}/cancel",
            body=self.client.write_body({"reason": "RFC smoke cancellation"}, operation="booking-cancel", dry_run=False, revision=self.revision),
        )
        replay_payload = self.client.request(
            "POST",
            "/api/availability:check",
            body={"target_type": "room", "target_id": "503", "start_at": start_at, "end_at": end_at},
        )
        replay_ok = replay_payload.get("data", {}).get("available") is True
        ok = cancel_payload.get("ok") is True and replay_ok
        self.record("booking_cancel_release", ok=ok, details={"booking_id": booking_id, "cancel_ok": cancel_payload.get("ok"), "replayed_available": replay_ok})
        self.remember_revision(cancel_payload)

    def check_nl_contract(self) -> None:
        configure_payload = self.client.request(
            "POST",
            "/api/nl/configure",
            body=self.client.write_body({"utterance": "这周三 504 下午临时维修"}, operation="nl-configure", dry_run=True, revision=self.revision),
        )
        candidates_payload = self.client.request(
            "POST",
            "/api/nl/bookings:candidates",
            body=self.client.write_body({"utterance": "下周二 10:00-11:00 想约一间小会议室"}, operation="nl-candidates", dry_run=True, revision=self.revision),
        )
        configure_data = configure_payload.get("data", {})
        candidates_data = candidates_payload.get("data", {})
        ok = configure_payload.get("ok") is True and candidates_payload.get("ok") is True and "parsed_changes" in configure_data and "candidates" in candidates_data
        self.record(
            "nl_contract",
            ok=ok,
            details={
                "configure_intent": configure_data.get("intent"),
                "matched_rule_id": configure_data.get("matched_rule_id"),
                "candidate_count": len(candidates_data.get("candidates", [])),
                "warnings": configure_payload.get("warnings", []) + candidates_payload.get("warnings", []),
            },
        )
        self.revision = max(self.meta_revision(configure_payload), self.meta_revision(candidates_payload))

    def check_calendar_floor_plan(self) -> None:
        start_at, _ = next_wednesday_window()
        query = parse.urlencode({"range_start": start_at, "range_end": start_at, "timezone": self.timezone_name})
        calendar_payload = self.client.request("GET", f"/api/calendar?{query}")
        floor_payload = self.client.request("GET", f"/api/floor-plan?date={start_at[:10]}&time={start_at[11:16]}")
        ok = calendar_payload.get("ok") is True and floor_payload.get("ok") is True and "slots" in calendar_payload.get("data", {}) and "rooms" in floor_payload.get("data", {})
        self.record("calendar_floor_plan", ok=ok, details={"calendar_slots": len(calendar_payload.get("data", {}).get("slots", [])), "floor_rooms": len(floor_payload.get("data", {}).get("rooms", []))})
        self.revision = max(self.meta_revision(calendar_payload), self.meta_revision(floor_payload))

    def check_agent_artifact_contract(self) -> None:
        agent_yaml = read_text("agent/meeting-agent/agent.yaml")
        tools_dir = list_dir("agent/meeting-agent/tools")
        required_tools = {
            "auth_meeting_api",
            "get_meeting_state",
            "query_availability",
            "check_availability",
            "nl_booking_candidates",
            "configure_meeting_state",
            "manage_rooms",
            "manage_rules",
            "manage_bookings",
            "get_calendar",
            "get_floor_plan",
        }
        missing_tools = required_tools - {path.replace(".tool.yaml", "") for path in tools_dir}
        required_bindings = {
            "auth_meeting_api": "custom_tools.meeting_tools:auth_meeting_api",
            "get_meeting_state": "custom_tools.meeting_tools:get_meeting_state",
            "query_availability": "custom_tools.meeting_tools:query_availability",
            "check_availability": "custom_tools.meeting_tools:check_availability",
            "nl_booking_candidates": "custom_tools.meeting_tools:nl_booking_candidates",
            "configure_meeting_state": "custom_tools.meeting_tools:configure_meeting_state",
            "manage_rooms": "custom_tools.meeting_tools:manage_rooms",
            "manage_rules": "custom_tools.meeting_tools:manage_rules",
            "manage_bookings": "custom_tools.meeting_tools:manage_bookings",
            "get_calendar": "custom_tools.meeting_tools:get_calendar",
            "get_floor_plan": "custom_tools.meeting_tools:get_floor_plan",
        }
        missing_bindings = {name: binding for name, binding in required_bindings.items() if binding not in agent_yaml}
        ok = not missing_tools and not missing_bindings
        self.record("agent_artifact_contract", ok=ok, details={"missing_tools": sorted(missing_tools), "missing_bindings": missing_bindings})

    def print_report(self) -> int:
        failed = [item for item in self.results if not item["ok"]]
        print(json.dumps({"ok": not failed, "revision": self.revision, "dry_run": self.dry_run, "results": self.results, "failed": failed}, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    def meta_revision(self, payload: dict[str, Any]) -> int:
        try:
            return int((payload.get("meta") or {}).get("state_revision", self.revision))
        except (TypeError, ValueError):
            return self.revision

    def remember_revision(self, payload: dict[str, Any]) -> None:
        self.revision = max(self.revision, self.meta_revision(payload))


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def list_dir(path: str) -> list[str]:
    return sorted(os.listdir(path))


def next_weekday(target_weekday: int, hour: int, minute: int, occurrence_index: int = 0) -> tuple[str, str]:
    now = datetime.now()
    found = -1
    delta = 0
    while found < occurrence_index:
        delta += 1
        candidate = datetime(now.year, now.month, now.day) + timedelta(days=delta)
        if candidate.weekday() == target_weekday:
            found += 1
    start = datetime(now.year, now.month, now.day, hour, minute) + timedelta(days=delta)
    end = start + timedelta(hours=1)
    return start.isoformat(), end.isoformat()


def next_workday_lunch_window() -> tuple[str, str]:
    current = datetime.now(UTC).astimezone(SHANGHAI)
    for day_offset in range(1, 10):
        candidate = current + timedelta(days=day_offset)
        if candidate.weekday() < 5:
            start = candidate.replace(hour=12, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
            return start.isoformat(), end.isoformat()
    raise AssertionError("could not find workday lunch window")


def next_tuesday_window() -> tuple[str, str]:
    return next_weekday(1, 10, 0)


def next_wednesday_window(occurrence_index: int = 0) -> tuple[str, str]:
    return next_weekday(2, 10, 0, occurrence_index)


def next_thursday_window(occurrence_index: int = 0) -> tuple[str, str]:
    return next_weekday(3, 10, 0, occurrence_index)


def tomorrow_lunch_window() -> tuple[str, str]:
    tomorrow = datetime.now() + timedelta(days=1)
    start = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return start.isoformat(), end.isoformat()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RFC-based smoke tests against the FastAPI meeting API.")
    parser.add_argument("--base-url", default=os.getenv("MEETING_API_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--username", default=os.getenv("MEETING_USERNAME", DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.getenv("MEETING_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--workspace-id", default=os.getenv("MEETING_WORKSPACE_ID", DEFAULT_WORKSPACE_ID))
    parser.add_argument("--actor-id", default=os.getenv("MEETING_ACTOR_ID", DEFAULT_ACTOR_ID))
    parser.add_argument("--timezone", default=os.getenv("TIMEZONE", DEFAULT_TIMEZONE))
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=os.getenv("MEETING_SMOKE_DRY_RUN", "true").lower() == "true")
    parser.add_argument("--allow-writes", action=argparse.BooleanOptionalAction, default=os.getenv("MEETING_SMOKE_ALLOW_WRITES", "false").lower() == "true", help="Run real create/cancel tests instead of dry-run-only write contract checks.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    login = request.Request(
        f"{args.base_url.rstrip('/')}/api/auth/login",
        data=json.dumps({"username": args.username, "password": args.password}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with request.urlopen(login, timeout=20.0) as response:  # noqa: S310 - local smoke test.
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("data", {}).get("token")
    if not token:
        print(json.dumps({"ok": False, "error": "login failed", "response": payload}, ensure_ascii=False, indent=2))
        return 1
    client = ApiClient(args.base_url, token, args.workspace_id, args.actor_id)
    return Runner(client, args.dry_run, args.timezone, args.allow_writes).run()


if __name__ == "__main__":
    raise SystemExit(main())

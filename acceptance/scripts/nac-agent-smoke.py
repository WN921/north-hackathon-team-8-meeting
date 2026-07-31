#!/usr/bin/env python3
"""Local smoke checks for the NAC meeting agent HTTP tool contract.

RFC-0005: NAC 云端会务 Agent 接入会务系统对接模式

This script intentionally does not call the real FastAPI service. It monkeypatches
the internal HTTP client so we can verify the request shape that NAC runtime will
send to FastAPI, including envelope fields for write operations.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = ROOT / "agent" / "meeting-agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from custom_tools import meeting_tools  # noqa: E402

CapturedRequest = dict[str, Any]


def _capture(captured: list[CapturedRequest]):
    def inner(
        tool_name: str,
        method: str,
        path: str,
        context: dict[str, Any],
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        captured.append(
            {
                "tool_name": tool_name,
                "method": method,
                "path": path,
                "body": body,
                "query": query,
            }
        )
        return {
            "ok": True,
            "request_id": f"smoke-{tool_name}",
            "data": {"available": True},
            "warnings": [],
            "meta": {"state_revision": 7, "server_time": "2026-07-31T12:00:00+08:00", "timezone": "Asia/Shanghai"},
        }

    return inner


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_query_availability_uses_fastapi_schema() -> None:
    captured: list[CapturedRequest] = []
    meeting_tools._http = _capture(captured)  # type: ignore[attr-defined]
    result = meeting_tools.query_availability(
        start_at="2026-08-05T10:00:00+08:00",
        end_at="2026-08-05T11:00:00+08:00",
        room_type="small",
        capacity=4,
        equipment=["screen"],
        allow_merge=True,
    )
    _assert(result["ok"] is True, "query_availability should succeed in smoke mode")
    _assert(captured[0]["path"] == "/api/availability:query", "query_availability should call POST /api/availability:query")
    body = captured[0]["body"]
    _assert(body["start_at"] == "2026-08-05T10:00:00+08:00", "query body should use start_at")
    _assert(body["end_at"] == "2026-08-05T11:00:00+08:00", "query body should use end_at")
    _assert(body["room_types"] == ["small"], "query body should map room_type to room_types")
    _assert("workspace_id" not in body and "actor_id" not in body, "query_availability should not send write envelope fields")


def test_check_availability_stays_read_only_for_fastapi() -> None:
    captured: list[CapturedRequest] = []
    meeting_tools._http = _capture(captured)  # type: ignore[attr-defined]
    result = meeting_tools.check_availability(
        start_at="2026-08-05T10:00:00+08:00",
        end_at="2026-08-05T11:00:00+08:00",
        target_type="room",
        target_id="room_503",
        booking_id="bk_existing",
        purpose="评审",
        expected_state_revision=6,
        idempotency_key="nac-meeting:smoke",
        dry_run=True,
    )
    _assert(result["ok"] is True, "check_availability should succeed in smoke mode")
    _assert(captured[0]["path"] == "/api/availability:check", "check_availability should call POST /api/availability:check")
    body = captured[0]["body"]
    _assert(body["start_at"] == "2026-08-05T10:00:00+08:00", "check body should use start_at")
    _assert(body["end_at"] == "2026-08-05T11:00:00+08:00", "check body should use end_at")
    _assert(body["target_type"] == "room" and body["target_id"] == "room_503", "check body should include selected target")
    _assert(body["booking_id"] == "bk_existing" and body["purpose"] == "评审", "check body should preserve FastAPI-supported optional fields")
    _assert("workspace_id" not in body and "actor_id" not in body, "check_availability should not send workspace_id/actor_id")
    _assert("idempotency_key" not in body and "dry_run" not in body, "check_availability should not send write envelope fields")


def test_write_tools_add_common_envelope() -> None:
    captured: list[CapturedRequest] = []
    meeting_tools._http = _capture(captured)  # type: ignore[attr-defined]
    os.environ["MEETING_WORKSPACE_ID"] = "default"
    os.environ["MEETING_ACTOR_ID"] = "demo-user"
    result = meeting_tools.manage_bookings(
        action="create",
        payload={"target_type": "room", "target_id": "room_503", "start_at": "2026-08-05T10:00:00+08:00", "end_at": "2026-08-05T11:00:00+08:00", "title": "评审会", "organizer_id": "demo-user"},
        expected_state_revision=6,
        idempotency_key="nac-meeting:smoke-booking",
        dry_run=True,
    )
    _assert(result["ok"] is True, "manage_bookings should succeed in smoke mode")
    body = captured[0]["body"]
    _assert(body["workspace_id"] == "default", "write body should include workspace_id")
    _assert(body["actor_id"] == "demo-user", "write body should include actor_id")
    _assert(body["expected_state_revision"] == 6, "write body should preserve expected_state_revision")
    _assert(body["idempotency_key"] == "nac-meeting:smoke-booking", "write body should preserve idempotency_key")
    _assert(body["dry_run"] is True, "write body should preserve dry_run")


def main() -> int:
    test_query_availability_uses_fastapi_schema()
    test_check_availability_stays_read_only_for_fastapi()
    test_write_tools_add_common_envelope()
    print("ok: NAC meeting agent local contract smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

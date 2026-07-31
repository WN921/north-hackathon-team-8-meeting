"""FastAPI-backed custom tools for the NAC meeting assistant.

RFC-0004: NAC 会务 Agent 制品与工具契约

The functions in this module are deliberately thin HTTP clients. They call the
FastAPI API boundary from RFC-0002 and never import SQLite repositories or domain
services. Write operations are enriched with workspace_id, actor_id,
idempotency_key, expected_state_revision, and dry_run where applicable.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any
from urllib import error, parse, request

DEFAULT_BASE_URL = "https://hackathon-8.qichangzheng.net"
DEFAULT_WORKSPACE_ID = "default"
DEFAULT_ACTOR_ID = "demo-user"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_TIMEZONE = "Asia/Shanghai"

WRITE_OPERATIONS = {
    "configure_meeting_state",
    "manage_rooms",
    "manage_rules",
    "manage_bookings",
}


class MeetingToolError(Exception):
    """Base exception for tool failures."""


def _read_context(
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id
        or os.getenv("MEETING_WORKSPACE_ID")
        or os.getenv("WORKSPACE_ID")
        or DEFAULT_WORKSPACE_ID,
        "actor_id": actor_id or os.getenv("MEETING_ACTOR_ID") or os.getenv("ACTOR_ID_FALLBACK") or DEFAULT_ACTOR_ID,
        "auth_token": auth_token or os.getenv("MEETING_AUTH_TOKEN") or os.getenv("AUTH_TOKEN"),
        "base_url": os.getenv("MEETING_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "timeout": float(os.getenv("MEETING_API_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        "timezone": os.getenv("TIMEZONE", DEFAULT_TIMEZONE),
    }


def _request_id(tool_name: str) -> str:
    return f"nac-{tool_name}-{uuid.uuid4().hex}"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _make_idempotency_key(
    context: dict[str, Any],
    operation_type: str,
    primary_resource_id: str | None,
    payload: dict[str, Any],
) -> str:
    normalized = {
        "workspace_id": context["workspace_id"],
        "actor_id": context["actor_id"],
        "operation_type": operation_type,
        "primary_resource_id": primary_resource_id,
        "payload": payload,
    }
    digest = _stable_hash(normalized)
    return f"nac-meeting:{context['workspace_id']}:{context['actor_id']}:{operation_type}:{primary_resource_id or 'none'}:{digest}"


def _success(
    tool_name: str,
    data: dict[str, Any],
    request_id: str,
    meta: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "request_id": request_id,
        "data": data,
        "warnings": warnings or [],
        "meta": {
            "state_revision": (meta or {}).get("state_revision"),
            "server_time": (meta or {}).get("server_time"),
            "timezone": (meta or {}).get("timezone", DEFAULT_TIMEZONE),
        },
    }


def _error(
    tool_name: str,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
    suggestions: list[str] | None = None,
    http_status: int | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "request_id": request_id,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "suggestions": suggestions or [],
            "http_status": http_status,
            "tool_name": tool_name,
            "recoverable": code not in {"INVALID_RESPONSE", "TOOL_EXCEPTION"},
            "next_action": _next_action(code),
        },
        "data": {},
        "warnings": [],
        "meta": {
            "state_revision": (meta or {}).get("state_revision"),
            "server_time": (meta or {}).get("server_time"),
            "timezone": (meta or {}).get("timezone", DEFAULT_TIMEZONE),
        },
    }


def _next_action(code: str) -> str:
    mapping = {
        "STATE_REVISION_CONFLICT": "重新读取当前会务状态，展示差异并请求用户再次确认。",
        "PROTECTED_RULE": "说明受保护规则不可删除或覆盖，建议改为新增/更新允许的规则。",
        "BOOKING_CONFLICT": "展示冲突详情，建议调整时间或选择其它候选房间。",
        "IDEMPOTENCY_KEY_REUSED": "不要复用该幂等键，重新生成与确认摘要一致的幂等键。",
        "UNAUTHORIZED": "请提供有效认证 token，或在明确 demo 模式下使用 auth_meeting_api。",
        "DEMO_REQUIRED": "当前操作需要显式 demo 登录；只读 demo 凭据不能用于写操作。",
        "LLM_PROVIDER_ERROR": "检查 FastAPI 后端自然语言 provider/model/API key 配置。",
        "TIMEOUT": "稍后重试，或确认 FastAPI 地址与网络连通性。",
        "TRANSPORT_ERROR": "确认 MEETING_API_BASE_URL 可达且网络正常。",
        "INVALID_RESPONSE": "检查 FastAPI 响应格式和 OpenAPI 契约。",
    }
    return mapping.get(code, "保留错误码并向用户说明失败来源和下一步。")


def _headers(context: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = context.get("auth_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http(
    tool_name: str,
    method: str,
    path: str,
    context: dict[str, Any],
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{context['base_url']}{path}"
    if query:
        clean_query = {key: value for key, value in query.items() if value is not None}
        if clean_query:
            url = f"{url}?{parse.urlencode(clean_query)}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, method=method.upper(), headers=_headers(context))
    rid = _request_id(tool_name)
    try:
        with request.urlopen(req, timeout=context["timeout"]) as response:  # noqa: S310 - caller controls URL from trusted deployment config.
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": {"code": "INVALID_RESPONSE", "message": raw or exc.reason}}
        return _normalize_response(tool_name, payload, rid, http_status=exc.code, error_override=None, meta=None)
    except error.URLError as exc:
        return _error(tool_name, "TRANSPORT_ERROR", f"FastAPI request failed: {exc.reason}", rid)
    except TimeoutError as exc:
        return _error(tool_name, "TIMEOUT", f"FastAPI request timed out: {exc}", rid)
    except json.JSONDecodeError:
        return _error(tool_name, "INVALID_RESPONSE", "FastAPI returned non-JSON response.", rid)
    except Exception as exc:  # pragma: no cover - defensive tool boundary.
        return _error(tool_name, "TOOL_EXCEPTION", f"Tool exception: {exc}", rid)
    return _normalize_response(tool_name, payload, rid, http_status=None)


def _normalize_response(
    tool_name: str,
    payload: dict[str, Any],
    rid: str,
    http_status: int | None = None,
    error_override: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _error(tool_name, "INVALID_RESPONSE", "FastAPI returned a non-object response.", rid, http_status=http_status, meta=meta)
    if not payload.get("ok", True):
        error_payload = payload.get("error") or error_override or {}
        if not isinstance(error_payload, dict):
            error_payload = {"code": "INVALID_RESPONSE", "message": str(error_payload)}
        merged = dict(error_payload)
        merged.setdefault("http_status", http_status)
        merged.setdefault("tool_name", tool_name)
        merged.setdefault("recoverable", True)
        merged.setdefault("next_action", _next_action(str(merged.get("code", "UNKNOWN_ERROR"))))
        return {
            "ok": False,
            "request_id": payload.get("request_id") or rid,
            "error": merged,
            "data": payload.get("data") or {},
            "warnings": payload.get("warnings") or [],
            "meta": {
                "state_revision": (payload.get("meta") or {}).get("state_revision", (meta or {}).get("state_revision")),
                "server_time": (payload.get("meta") or {}).get("server_time", (meta or {}).get("server_time")),
                "timezone": (payload.get("meta") or {}).get("timezone", (meta or {}).get("timezone", DEFAULT_TIMEZONE)),
            },
        }
    response_meta = payload.get("meta") or meta or {}
    warnings = list(payload.get("warnings") or [])
    if not response_meta.get("state_revision") or not response_meta.get("server_time"):
        warnings.append("missing_meta")
    return _success(tool_name, payload.get("data") or {}, payload.get("request_id") or rid, response_meta, warnings)


def _with_common_write_fields(
    context: dict[str, Any],
    payload: dict[str, Any] | None,
    operation_type: str,
    primary_resource_id: str | None,
    idempotency_key: str | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    body = dict(payload or {})
    body.setdefault("workspace_id", context["workspace_id"])
    body.setdefault("actor_id", context["actor_id"])
    body.setdefault("expected_state_revision", None)
    body.setdefault("idempotency_key", idempotency_key or _make_idempotency_key(context, operation_type, primary_resource_id, body))
    if dry_run is not None:
        body.setdefault("dry_run", dry_run)
    return body


def _auth_meeting_api_login(context: dict[str, Any]) -> dict[str, Any]:
    # RFC-0004: explicit demo mode only; credentials are injected by deployment,
    # not hard-coded into the artifact.
    demo_credentials = os.getenv("MEETING_DEMO_CREDENTIALS")
    if demo_credentials:
        try:
            credentials = json.loads(demo_credentials)
        except json.JSONDecodeError:
            return _error("auth_meeting_api", "INVALID_RESPONSE", "MEETING_DEMO_CREDENTIALS must be JSON.", _request_id("auth_meeting_api"))
    else:
        credentials = {
            "username": os.getenv("MEETING_DEMO_USERNAME", "demo-user"),
            "password": os.getenv("MEETING_DEMO_PASSWORD", "demo-password"),
        }
    credentials.setdefault("workspace_id", context["workspace_id"])
    body = {"username": credentials.get("username"), "password": credentials.get("password"), "workspace_id": context["workspace_id"]}
    result = _http("auth_meeting_api", "POST", "/api/auth/login", context, body)
    if result["ok"]:
        result["data"] = dict(result.get("data") or {})
        result["data"]["demo_actor"] = True
    return result


def auth_meeting_api(
    action: str,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    token: str | None = None,
    demo_actor: bool | None = None,
) -> dict[str, Any]:
    """Log in, log out, or read the current user for explicit demo auth mode."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=token)
    if action == "login":
        return _auth_meeting_api_login(context)
    if action == "logout":
        return _http("auth_meeting_api", "POST", "/api/auth/logout", context)
    if action == "me":
        return _http("auth_meeting_api", "GET", "/api/auth/me", context)
    return _error("auth_meeting_api", "INVALID_ARGUMENT", "action must be login, logout, or me.", _request_id("auth_meeting_api"))


def get_meeting_state(
    include_health: bool = True,
    include_rooms: bool = True,
    include_rules: bool = True,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Read health, rooms, composites, and rules through FastAPI."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    rid = _request_id("get_meeting_state")
    data: dict[str, Any] = {}
    warnings: list[str] = []
    latest_meta: dict[str, Any] = {}
    for key, include, method, path in (
        ("health", include_health, "GET", "/api/health"),
        ("rooms", include_rooms, "GET", "/api/rooms"),
        ("rules", include_rules, "GET", "/api/rules"),
    ):
        if not include:
            continue
        result = _http("get_meeting_state", method, path, context)
        if not result.get("ok"):
            data[f"{key}_error"] = result.get("error")
            warnings.append(f"{key}_request_failed:{result.get('error', {}).get('code')}")
            continue
        data[key] = result.get("data") or {}
        meta = result.get("meta") or {}
        if meta.get("state_revision") is not None:
            latest_meta = meta
    if not data:
        return _error("get_meeting_state", "TRANSPORT_ERROR", "All meeting state sub-requests failed.", rid, meta=latest_meta)
    return _success("get_meeting_state", data, rid, latest_meta or None, warnings)


def query_availability(
    start_time: str,
    end_time: str,
    target_type: str | None = None,
    target_id: str | None = None,
    room_type: str | None = None,
    purpose: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Query available targets for a time window."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    payload = {"start_time": start_time, "end_time": end_time}
    if target_type:
        payload["target_type"] = target_type
    if target_id:
        payload["target_id"] = target_id
    if room_type:
        payload["room_type"] = room_type
    if purpose:
        payload["purpose"] = purpose
    return _http("query_availability", "POST", "/api/availability:query", context, payload)


def check_availability(
    start_time: str,
    end_time: str,
    target_type: str,
    target_id: str,
    booking_id: str | None = None,
    purpose: str | None = None,
    expected_state_revision: int | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Pre-check a selected target before booking changes."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    payload = {
        "start_time": start_time,
        "end_time": end_time,
        "target_type": target_type,
        "target_id": target_id,
    }
    if booking_id:
        payload["booking_id"] = booking_id
    if purpose:
        payload["purpose"] = purpose
    if expected_state_revision is not None:
        payload["expected_state_revision"] = expected_state_revision
    return _http("check_availability", "POST", "/api/availability:check", context, payload)


def nl_booking_candidates(
    user_message: str,
    session_id: str | None = None,
    dry_run: bool | None = True,
    expected_state_revision: int | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Parse natural-language booking intent and return candidates."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    payload = {"user_message": user_message}
    if session_id:
        payload["session_id"] = session_id
    if dry_run is not None:
        payload["dry_run"] = dry_run
    if expected_state_revision is not None:
        payload["expected_state_revision"] = expected_state_revision
    return _http("nl_booking_candidates", "POST", "/api/nl/bookings:candidates", context, payload)


def configure_meeting_state(
    user_message: str,
    dry_run: bool,
    session_id: str | None = None,
    expected_state_revision: int | None = None,
    idempotency_key: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Preview or apply natural-language meeting state configuration."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    payload = {"user_message": user_message}
    if session_id:
        payload["session_id"] = session_id
    payload = _with_common_write_fields(
        context,
        payload,
        "configure_meeting_state",
        None,
        idempotency_key=idempotency_key,
        dry_run=dry_run,
    )
    if expected_state_revision is not None:
        payload["expected_state_revision"] = expected_state_revision
    return _http("configure_meeting_state", "POST", "/api/nl/configure", context, payload)


def manage_rooms(
    action: str,
    room_id: str | None = None,
    schedule_id: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_state_revision: int | None = None,
    idempotency_key: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Manage rooms, composites, and opening schedules."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    rid = _request_id("manage_rooms")
    if action == "list":
        return _http("manage_rooms", "GET", "/api/rooms", context)
    if action == "get" and room_id:
        return _http("manage_rooms", "GET", f"/api/rooms/{room_id}", context)
    if action == "create":
        body = _with_common_write_fields(context, payload, "create_room", None, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rooms", "POST", "/api/rooms", context, body)
    if action == "update" and room_id:
        body = _with_common_write_fields(context, payload, "update_room", room_id, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rooms", "PATCH", f"/api/rooms/{room_id}", context, body)
    if action == "create_opening_schedule" and room_id:
        body = _with_common_write_fields(context, payload, "create_opening_schedule", room_id, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rooms", "POST", f"/api/rooms/{room_id}/opening-schedules", context, body)
    if action == "update_opening_schedule" and room_id and schedule_id:
        body = _with_common_write_fields(context, payload, "update_opening_schedule", f"{room_id}:{schedule_id}", idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rooms", "PATCH", f"/api/rooms/{room_id}/opening-schedules/{schedule_id}", context, body)
    if action == "delete_opening_schedule" and room_id and schedule_id:
        body = _with_common_write_fields(context, {}, "delete_opening_schedule", f"{room_id}:{schedule_id}", idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rooms", "DELETE", f"/api/rooms/{room_id}/opening-schedules/{schedule_id}", context, body)
    return _error("manage_rooms", "INVALID_ARGUMENT", "Unsupported room action or missing id.", rid)


def manage_rules(
    action: str,
    rule_id: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_state_revision: int | None = None,
    idempotency_key: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Manage rules through FastAPI."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    rid = _request_id("manage_rules")
    if action == "list":
        return _http("manage_rules", "GET", "/api/rules", context)
    if action == "get" and rule_id:
        return _http("manage_rules", "GET", f"/api/rules/{rule_id}", context)
    if action == "create":
        body = _with_common_write_fields(context, payload, "create_rule", None, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rules", "POST", "/api/rules", context, body)
    if action == "update" and rule_id:
        body = _with_common_write_fields(context, payload, "update_rule", rule_id, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rules", "PATCH", f"/api/rules/{rule_id}", context, body)
    if action == "delete" and rule_id:
        body = _with_common_write_fields(context, {}, "delete_rule", rule_id, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_rules", "DELETE", f"/api/rules/{rule_id}", context, body)
    return _error("manage_rules", "INVALID_ARGUMENT", "Unsupported rule action or missing id.", rid)


def manage_bookings(
    action: str,
    booking_id: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_state_revision: int | None = None,
    idempotency_key: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Manage bookings through FastAPI."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    rid = _request_id("manage_bookings")
    if action == "list":
        return _http("manage_bookings", "GET", "/api/bookings", context)
    if action == "get" and booking_id:
        return _http("manage_bookings", "GET", f"/api/bookings/{booking_id}", context)
    if action == "create":
        body = _with_common_write_fields(context, payload, "create_booking", None, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_bookings", "POST", "/api/bookings", context, body)
    if action == "cancel" and booking_id:
        body = _with_common_write_fields(context, {}, "cancel_booking", booking_id, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_bookings", "POST", f"/api/bookings/{booking_id}/cancel", context, body)
    if action == "update" and booking_id:
        body = _with_common_write_fields(context, payload, "update_booking", booking_id, idempotency_key=idempotency_key)
        if expected_state_revision is not None:
            body["expected_state_revision"] = expected_state_revision
        return _http("manage_bookings", "PATCH", f"/api/bookings/{booking_id}", context, body)
    return _error("manage_bookings", "INVALID_ARGUMENT", "Unsupported booking action or missing id.", rid)


def get_calendar(
    start_date: str,
    end_date: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Read calendar state for a date range."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    query = {"start_date": start_date}
    if end_date:
        query["end_date"] = end_date
    if target_type:
        query["target_type"] = target_type
    if target_id:
        query["target_id"] = target_id
    return _http("get_calendar", "GET", "/api/calendar", context, query=query)


def get_floor_plan(
    date: str | None = None,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Read floor-plan nodes and status."""
    context = _read_context(workspace_id=workspace_id, actor_id=actor_id, auth_token=auth_token)
    query = {"date": date} if date else None
    return _http("get_floor_plan", "GET", "/api/floor-plan", context, query=query)

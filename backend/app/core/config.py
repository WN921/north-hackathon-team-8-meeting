"""Core constants and utilities for the FastAPI backend. RFC-0002."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

ZONE_NAME = "Asia/Shanghai"


class ErrorCode(StrEnum):
    """Structured API error codes required by RFC-0002."""

    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NATURAL_LANGUAGE_AMBIGUOUS = "NATURAL_LANGUAGE_AMBIGUOUS"
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    COMPOSITE_NOT_FOUND = "COMPOSITE_NOT_FOUND"
    BOOKING_NOT_FOUND = "BOOKING_NOT_FOUND"
    RULE_NOT_FOUND = "RULE_NOT_FOUND"
    STATE_REVISION_CONFLICT = "STATE_REVISION_CONFLICT"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    BOOKING_CONFLICT = "BOOKING_CONFLICT"
    BOOKING_BLOCKED_BY_RULE = "BOOKING_BLOCKED_BY_RULE"
    OUTSIDE_OPENING_HOURS = "OUTSIDE_OPENING_HOURS"
    PROTECTED_RULE = "PROTECTED_RULE"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class ReasonCode(StrEnum):
    """Business reason codes shared by availability, calendar and floor-plan APIs."""

    FIXED_UNAVAILABLE = "FIXED_UNAVAILABLE"
    WEEKLY_UNAVAILABLE = "WEEKLY_UNAVAILABLE"
    TEMPORARY_MAINTENANCE = "TEMPORARY_MAINTENANCE"
    OVERLAPPING_BOOKING = "OVERLAPPING_BOOKING"
    OVERLAPPING_COMPOSITE_BOOKING = "OVERLAPPING_COMPOSITE_BOOKING"
    COMPOSITE_BOOKED = "COMPOSITE_BOOKED"
    OUTSIDE_OPENING_HOURS = "OUTSIDE_OPENING_HOURS"


DEFAULT_WORKSPACE_ID = "default"
DEFAULT_ACTOR_ID = "user_001"
DEFAULT_TIMEZONE = ZONE_NAME
EXPECTED_LLM_PROVIDER = "nex-agi"
EXPECTED_LLM_MODEL = "Nex-N2-Pro"


def llm_runtime_config() -> dict[str, str | bool | None]:
    """Read the local Agent runtime configuration required by RFC-0002."""

    api_key_present = bool(os.getenv("NEX_AGI_API_KEY"))
    return {
        "provider": os.getenv("LLM_PROVIDER", EXPECTED_LLM_PROVIDER),
        "model": os.getenv("LLM_MODEL", EXPECTED_LLM_MODEL),
        "api_key_present": api_key_present,
        "configured": api_key_present,
    }


def expected_llm_config() -> dict[str, str | bool]:
    """Return the RFC-0002 required Agent runtime configuration."""

    return {
        "provider": EXPECTED_LLM_PROVIDER,
        "model": EXPECTED_LLM_MODEL,
        "api_key_present": True,
        "configured": True,
    }


def validate_llm_runtime_config() -> dict[str, str | None]:
    """Validate Nex-N2-Pro runtime configuration and raise if it is missing."""

    from app.services.api_service import APIError

    runtime = llm_runtime_config()
    expected = expected_llm_config()
    missing = [key for key, value in runtime.items() if bool(value) != expected[key]]
    if missing:
        raise APIError(
            ErrorCode.LLM_PROVIDER_ERROR,
            "Nex-N2-Pro Agent runtime 未配置",
            {"missing": missing, "required": expected, "actual": runtime},
            ["请设置 LLM_PROVIDER=nex-agi、LLM_MODEL=Nex-N2-Pro 和 NEX_AGI_API_KEY"],
            502,
        )
    return runtime


def utc_now() -> datetime:
    """Return timezone-aware UTC now for request metadata."""

    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Return RFC-0002 metadata timestamp in ISO-8601 format."""

    return utc_now().isoformat()


def request_id(prefix: str = "req") -> str:
    """Generate a stable-looking request identifier for API responses."""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable without failing in local tests."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def stable_hash(value: Any) -> str:
    """Create a deterministic hash for idempotency request comparison."""

    import json

    return uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(value, sort_keys=True, default=str)).hex

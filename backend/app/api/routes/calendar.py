"""Calendar route for RFC-0002."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, RepositoryDep
from app.core.config import DEFAULT_TIMEZONE, now_iso, request_id
from app.schemas.api import ApiMeta, SuccessResponse

router = APIRouter(prefix="/api", tags=["Calendar"])


@router.get("/calendar", response_model=SuccessResponse)
def get_calendar(repository: RepositoryDep, _: CurrentUserDep, target_type: str | None = None, target_id: str | None = None, date: str | None = None, range_start: str | None = None, range_end: str | None = None, include_bookings: bool = True, include_rules: bool = True, include_fixed_blocks: bool = True) -> SuccessResponse:
    slots = []
    if include_bookings:
        for booking in repository.list_bookings(target_type=target_type, target_id=target_id, date=date, range_start=range_start, range_end=range_end, status="confirmed", limit=100):
            slots.append({"start_at": booking.start_at, "end_at": booking.end_at, "status": "booked", "target_type": booking.target_type, "target_id": booking.target_id, "booking_id": booking.id, "title": booking.title})
    if include_rules:
        for rule in repository.list_rules(target_type=target_type, target_id=target_id, date=date, limit=100):
            if not include_fixed_blocks and rule.fixed:
                continue
            for window in rule.time_windows:
                slots.append({"start_at": window.start_at, "end_at": window.end_at, "status": "fixed_unavailable" if rule.fixed else "blocked_by_rule", "target_type": rule.target_type, "target_id": rule.target_id, "rule_id": rule.id, "reason_code": rule.reason_code(), "message": rule.reason})
    return SuccessResponse(ok=True, request_id=request_id("req_calendar"), data={"slots": slots}, meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))

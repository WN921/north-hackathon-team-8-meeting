"""Booking routes for RFC-0002."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, RepositoryDep
from app.core.config import DEFAULT_TIMEZONE, ErrorCode, now_iso, request_id
from app.domain.models import Booking
from app.schemas.api import ApiMeta, BookingCreateRequest, BookingUpdateRequest, CancelBookingRequest, SuccessResponse
from app.services.api_service import APIError, availability, availability_error_code, check_idempotency, save_idempotency, validate_state_revision

router = APIRouter(prefix="/api/bookings", tags=["Bookings"])


@router.get("", response_model=SuccessResponse)
def list_bookings(repository: RepositoryDep, _: CurrentUserDep, target_type: str | None = None, target_id: str | None = None, actor_id: str | None = None, date: str | None = None, range_start: str | None = None, range_end: str | None = None, status: str | None = None, limit: int = Query(50, ge=1, le=500)) -> SuccessResponse:
    bookings = repository.list_bookings(target_type=target_type, target_id=target_id, actor_id=actor_id, date=date, range_start=range_start, range_end=range_end, status=status, limit=limit)
    return SuccessResponse(ok=True, request_id=request_id("req_bookings"), data={"items": [booking.to_dict() for booking in bookings]}, meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))


@router.get("/{booking_id}", response_model=SuccessResponse)
def get_booking(booking_id: str, repository: RepositoryDep, _: CurrentUserDep) -> SuccessResponse:
    booking = repository.get_booking(booking_id)
    if booking is None:
        raise APIError(ErrorCode.BOOKING_NOT_FOUND, "预约不存在", {"booking_id": booking_id}, ["请检查预约 ID"], 404)
    return SuccessResponse(ok=True, request_id=request_id("req_booking_detail"), data=booking.to_dict(), meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))


@router.post("", response_model=SuccessResponse)
def create_booking(payload: BookingCreateRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    target_type, target_id = payload.normalized_target()
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    check = availability(repository, target_type, target_id, payload.start_at, payload.end_at)
    if not check["available"]:
        raise APIError(availability_error_code(check), "创建预约失败", check, ["请选择其他房间或时段"], 409)
    booking = repository.create_booking(Booking(id=f"bk_{uuid.uuid4().hex}", target_type=target_type, target_id=target_id, start_at=payload.start_at, end_at=payload.end_at, title=payload.title, organizer_id=payload.organizer_id, attendees=payload.attendees, description=payload.description), payload.idempotency_key, user.id)
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_create_booking"), data={"booking_id": booking.id, "status": booking.status, "target_type": booking.target_type, "target_id": booking.target_id, "target_name": booking.target_id, "start_at": booking.start_at, "end_at": booking.end_at, "conflicts": []}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.post("/{booking_id}/cancel", response_model=SuccessResponse)
def cancel_booking(booking_id: str, payload: CancelBookingRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    booking = repository.get_booking(booking_id)
    if booking is None:
        raise APIError(ErrorCode.BOOKING_NOT_FOUND, "预约不存在", {"booking_id": booking_id}, ["请检查预约 ID"], 404)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    updated = repository.update_booking(booking_id, status="cancelled", reason=payload.reason)
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_cancel_booking"), data={"booking_id": booking_id, "status": updated.status, "released_slots": [{"target_type": updated.target_type, "target_id": updated.target_id, "start_at": updated.start_at, "end_at": updated.end_at}]}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.patch("/{booking_id}", response_model=SuccessResponse)
def update_booking(booking_id: str, payload: BookingUpdateRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    booking = repository.get_booking(booking_id)
    if booking is None:
        raise APIError(ErrorCode.BOOKING_NOT_FOUND, "预约不存在", {"booking_id": booking_id}, ["请检查预约 ID"], 404)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    target = payload.normalized_target()
    target_type = target[0] if target else booking.target_type
    target_id = target[1] if target else booking.target_id
    start_at = payload.start_at or booking.start_at
    end_at = payload.end_at or booking.end_at
    check = availability(repository, target_type, target_id, start_at, end_at, exclude_booking_id=booking_id)
    if not check["available"]:
        raise APIError(availability_error_code(check), "修改预约失败", check, ["请选择其他房间或时段"], 409)
    updated = repository.update_booking(booking_id, target_type=target_type, target_id=target_id, start_at=start_at, end_at=end_at, title=payload.title or booking.title, reason=payload.reason)
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_update_booking"), data={"booking_id": booking_id, "status": "updated", "target_type": updated.target_type, "target_id": updated.target_id, "target_name": updated.target_id, "old_booking": booking.to_dict(), "new_booking": updated.to_dict(), "conflicts": []}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response

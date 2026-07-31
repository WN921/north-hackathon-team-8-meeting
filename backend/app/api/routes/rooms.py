"""Room and availability routes for RFC-0002."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, RepositoryDep
from app.core.config import DEFAULT_TIMEZONE, ErrorCode, now_iso, request_id
from app.domain.models import Room, TimeWindow
from app.schemas.api import (
    AvailabilityCheck,
    AvailabilityQuery,
    ApiMeta,
    OpeningScheduleCreateRequest,
    OpeningScheduleDeleteRequest,
    OpeningSchedulePatchRequest,
    Position,
    RoomCreateRequest,
    RoomPatchRequest,
    SuccessResponse,
)
from app.services.api_service import APIError, availability, availability_error_code, check_idempotency, list_available_targets, save_idempotency, validate_state_revision, get_room_or_error

router = APIRouter(prefix="/api", tags=["Rooms", "Availability"])


@router.get("/rooms", response_model=SuccessResponse)
def list_rooms(
    repository: RepositoryDep,
    _: CurrentUserDep,
    include_composite: bool = Query(False),
    date: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    capacity: int | None = None,
    equipment: list[str] | None = Query(None),
    room_type: str | None = None,
) -> SuccessResponse:
    rooms, composites = repository.list_rooms(include_composite=include_composite, date=date, start_at=start_at, end_at=end_at, capacity=capacity, equipment=equipment, room_type=room_type)
    return SuccessResponse(
        ok=True,
        request_id=request_id("req_rooms"),
        data={"rooms": [room.to_dict() for room in rooms], "composites": [composite.to_dict() for composite in composites]},
        meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone=DEFAULT_TIMEZONE),
    )


@router.post("/rooms", response_model=SuccessResponse)
def create_room(payload: RoomCreateRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    if payload.dry_run:
        room = Room(
            id=payload.id,
            name=payload.name,
            type=payload.type,
            location=payload.location,
            capacity=payload.capacity,
            equipment=payload.equipment,
            position=Position(**payload.position.model_dump()) if payload.position else None,
            protected=payload.protected,
            active=payload.active,
        )
        response = SuccessResponse(ok=True, request_id=request_id("req_room_create"), data={"room": room.to_dict(), "dry_run": True}, meta=ApiMeta(state_revision=repository.get_state_revision(payload.workspace_id), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
        save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
        return response
    room = repository.upsert_room(
        Room(
            id=payload.id,
            name=payload.name,
            type=payload.type,
            location=payload.location,
            capacity=payload.capacity,
            equipment=payload.equipment,
            position=Position(**payload.position.model_dump()) if payload.position else None,
            protected=payload.protected,
            active=payload.active,
        )
    )
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_room_create"), data={"room": room.to_dict()}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.patch("/rooms/{room_id}", response_model=SuccessResponse)
def patch_room(room_id: str, payload: RoomPatchRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    room = get_room_or_error(repository, room_id)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    updated = Room(
        id=room.id,
        name=payload.name or room.name,
        type=payload.type or room.type,
        location=payload.location or room.location,
        capacity=payload.capacity if payload.capacity is not None else room.capacity,
        equipment=payload.equipment if payload.equipment is not None else room.equipment,
        position=payload.position or room.position,
        protected=room.protected,
        active=payload.active if payload.active is not None else room.active,
    )
    if payload.dry_run:
        response = SuccessResponse(ok=True, request_id=request_id("req_room_update"), data={"room": updated.to_dict(), "dry_run": True}, meta=ApiMeta(state_revision=repository.get_state_revision(payload.workspace_id), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
        save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
        return response
    updated = repository.upsert_room(updated)
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_room_update"), data={"room": updated.to_dict()}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.post("/rooms/{room_id}/opening-schedules", response_model=SuccessResponse)
def create_opening_schedule(room_id: str, payload: OpeningScheduleCreateRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    get_room_or_error(repository, room_id)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    schedule = {"id": f"sch_{room_id}_{payload.weekday}", "room_id": room_id, "weekday": payload.weekday, "start_time": payload.start_time, "end_time": payload.end_time}
    if payload.dry_run:
        response = SuccessResponse(ok=True, request_id=request_id("req_room_opening"), data={"opening_schedule": schedule, "dry_run": True}, meta=ApiMeta(state_revision=repository.get_state_revision(payload.workspace_id), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
        save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
        return response
    schedule = repository.upsert_opening_schedule(room_id, payload.weekday, payload.start_time, payload.end_time)
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_room_opening"), data={"opening_schedule": schedule}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.patch("/rooms/{room_id}/opening-schedules/{schedule_id}", response_model=SuccessResponse)
def patch_opening_schedule(room_id: str, schedule_id: str, payload: OpeningSchedulePatchRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    try:
        schedule = repository.patch_opening_schedule(schedule_id, room_id, payload.weekday, payload.start_time, payload.end_time)
    except KeyError:
        raise APIError(ErrorCode.VALIDATION_ERROR, "开放时段不存在", {"schedule_id": schedule_id}, ["请检查开放时段 ID"], 404)
    except ValueError:
        raise APIError(ErrorCode.PROTECTED_RULE, "固定开放时段不可修改", {"schedule_id": schedule_id}, ["固定规则不可修改"], 409)
    if payload.dry_run:
        response = SuccessResponse(ok=True, request_id=request_id("req_room_opening_update"), data={"opening_schedule": schedule, "dry_run": True}, meta=ApiMeta(state_revision=repository.get_state_revision(payload.workspace_id), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
        save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
        return response
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_room_opening_update"), data={"opening_schedule": schedule}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.delete("/rooms/{room_id}/opening-schedules/{schedule_id}", response_model=SuccessResponse)
def delete_opening_schedule(room_id: str, schedule_id: str, payload: OpeningScheduleDeleteRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    try:
        repository.delete_opening_schedule(schedule_id)
    except KeyError:
        raise APIError(ErrorCode.VALIDATION_ERROR, "开放时段不存在", {"schedule_id": schedule_id}, ["请检查开放时段 ID"], 404)
    except ValueError:
        raise APIError(ErrorCode.PROTECTED_RULE, "固定开放时段不可删除", {"schedule_id": schedule_id}, ["固定规则不可删除"], 409)
    if payload.dry_run:
        response = SuccessResponse(ok=True, request_id=request_id("req_room_opening_delete"), data={"deleted": True, "schedule_id": schedule_id, "dry_run": True}, meta=ApiMeta(state_revision=repository.get_state_revision(payload.workspace_id), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
        save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
        return response
    revision = repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_room_opening_delete"), data={"deleted": True, "schedule_id": schedule_id}, meta=ApiMeta(state_revision=revision, server_time=now_iso(), timezone=DEFAULT_TIMEZONE))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.post("/availability:query", response_model=SuccessResponse)
def availability_query(payload: AvailabilityQuery, repository: RepositoryDep, _: CurrentUserDep) -> SuccessResponse:
    data = list_available_targets(repository, payload.start_at, payload.end_at, payload.capacity, payload.equipment, payload.room_types, payload.allow_merge)
    return SuccessResponse(ok=True, request_id=request_id("req_availability_query"), data=data, meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone=payload.timezone))


@router.post("/availability:check", response_model=SuccessResponse)
def availability_check(payload: AvailabilityCheck, repository: RepositoryDep, _: CurrentUserDep) -> SuccessResponse:
    data = availability(repository, payload.target_type, payload.target_id, payload.start_at, payload.end_at, payload.capacity, payload.equipment)
    if not data["available"]:
        raise APIError(availability_error_code(data), "目标在指定时段不可预约", data, ["请选择其他房间或时段"], 409)
    return SuccessResponse(ok=True, request_id=request_id("req_availability_check"), data=data, meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone=DEFAULT_TIMEZONE))

"""Pydantic request and response schemas for RFC-0002 API endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TargetType = Literal["room", "composite"]
RuleType = Literal["fixed_unavailable", "weekly_unavailable", "temporary_maintenance"]


class UserOut(BaseModel):
    id: str
    name: str
    role: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponseData(BaseModel):
    user: UserOut
    token: str


class ApiMeta(BaseModel):
    state_revision: int
    server_time: str
    timezone: str = "Asia/Shanghai"


class SuccessResponse(BaseModel):
    ok: Literal[True]
    request_id: str
    data: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    meta: ApiMeta


class ErrorResponse(BaseModel):
    ok: Literal[False]
    request_id: str
    error: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    meta: ApiMeta


class WriteEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = "default"
    actor_id: str
    idempotency_key: str
    expected_state_revision: int
    dry_run: bool = False


class DeleteEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = "default"
    actor_id: str
    idempotency_key: str
    expected_state_revision: int
    dry_run: bool = False


class Position(BaseModel):
    x: int
    y: int
    width: int
    height: int


class RoomOut(BaseModel):
    id: str
    name: str
    type: str
    location: str
    capacity: int
    equipment: list[str]
    position: Position | None
    status: str = "available"
    protected: bool
    active: bool = True


class CompositeOut(BaseModel):
    id: str
    name: str
    member_room_ids: list[str]
    capacity: int
    equipment: list[str]
    position: Position | None
    status: str = "available"
    protected: bool
    active: bool = True


class RoomCreate(BaseModel):
    id: str
    name: str
    type: str
    location: str = "5F"
    capacity: int
    equipment: list[str] = Field(default_factory=list)
    position: Position | None = None
    protected: bool = False
    active: bool = True


class RoomCreateRequest(RoomCreate, WriteEnvelope):
    pass


class RoomPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    capacity: int | None = None
    equipment: list[str] | None = None
    location: str | None = None
    position: Position | None = None
    active: bool | None = None


class RoomPatchRequest(RoomPatch, WriteEnvelope):
    pass


class OpeningScheduleCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: str
    end_time: str


class OpeningScheduleCreateRequest(OpeningScheduleCreate, WriteEnvelope):
    pass


class OpeningSchedulePatch(OpeningScheduleCreate):
    pass


class OpeningSchedulePatchRequest(OpeningSchedulePatch, WriteEnvelope):
    pass


class OpeningScheduleDeleteRequest(DeleteEnvelope):
    pass


class RuleWindowIn(BaseModel):
    start_at: str
    end_at: str
    recurrence: str | None = None


class RuleCreate(BaseModel):
    rule_type: RuleType
    target_type: TargetType
    target_id: str
    time_windows: list[RuleWindowIn]
    reason: str
    match_key: str | None = None
    rule_id: str | None = None


class RuleCreateRequest(RuleCreate, WriteEnvelope):
    pass


class RulePatch(BaseModel):
    rule_type: RuleType | None = None
    target_type: TargetType | None = None
    target_id: str | None = None
    time_windows: list[RuleWindowIn] | None = None
    reason: str | None = None
    match_key: str | None = None


class RulePatchRequest(RulePatch, WriteEnvelope):
    pass


class RuleDeleteRequest(DeleteEnvelope):
    pass


class AvailabilityTarget(BaseModel):
    target_type: TargetType
    target_id: str
    start_at: str
    end_at: str
    capacity: int | None = None
    equipment: list[str] = Field(default_factory=list)
    room_types: list[str] = Field(default_factory=list)
    allow_merge: bool = False


class AvailabilityQuery(BaseModel):
    start_at: str
    end_at: str
    timezone: str = "Asia/Shanghai"
    capacity: int | None = None
    equipment: list[str] = Field(default_factory=list)
    room_types: list[str] = Field(default_factory=list)
    allow_merge: bool = False


class AvailabilityCheck(BaseModel):
    target_type: TargetType
    target_id: str
    start_at: str
    end_at: str
    capacity: int | None = None
    equipment: list[str] = Field(default_factory=list)


class BookingCreate(BaseModel):
    target_type: TargetType | None = None
    target_id: str | None = None
    room_id: str | None = None
    composite_id: str | None = None
    start_at: str
    end_at: str
    title: str
    organizer_id: str
    attendees: list[str] = Field(default_factory=list)
    description: str = ""

    def normalized_target(self) -> tuple[str, str]:
        supplied = [self.target_type, self.target_id, self.room_id, self.composite_id]
        if self.target_type is None and self.target_id is None and self.room_id is None and self.composite_id is None:
            raise ValueError("target_id, room_id or composite_id is required")
        target_type = self.target_type or ("composite" if self.composite_id else "room")
        target_id = self.target_id or self.composite_id or self.room_id or ""
        if not target_id:
            raise ValueError("target_id, room_id or composite_id is required")
        if (self.composite_id and target_type != "composite") or (self.room_id and target_type != "room"):
            raise ValueError("target_type must match room_id or composite_id")
        if self.target_id and self.target_type is None:
            raise ValueError("target_type is required when using target_id")
        if supplied.count(None) < 2 and self.target_id and (self.room_id or self.composite_id):
            raise ValueError("use either target_id or room_id/composite_id, not both")
        return target_type, target_id

    def model_post_init(self, __context: Any) -> None:
        if self.target_type is None and (self.composite_id or self.room_id):
            self.target_type = "composite" if self.composite_id else "room"
        if self.target_id is None and (self.composite_id or self.room_id):
            self.target_id = self.composite_id or self.room_id
        if self.target_id and self.target_type is None:
            raise ValueError("target_type is required when using target_id")
        if self.target_id and (self.room_id or self.composite_id) and self.target_id not in {self.room_id, self.composite_id}:
            raise ValueError("target_id must match room_id or composite_id")
        if (self.composite_id and self.target_type != "composite") or (self.room_id and self.target_type != "room"):
            raise ValueError("target_type must match room_id or composite_id")


class BookingCreateRequest(BookingCreate, WriteEnvelope):
    pass


class BookingUpdate(BaseModel):
    title: str | None = None
    target_type: TargetType | None = None
    target_id: str | None = None
    room_id: str | None = None
    composite_id: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    reason: str | None = None

    def normalized_target(self) -> tuple[str, str] | None:
        if self.target_type is None and self.target_id is None and self.room_id is None and self.composite_id is None:
            return None
        target_type = self.target_type or ("composite" if self.composite_id else "room")
        target_id = self.target_id or self.composite_id or self.room_id or ""
        if not target_id:
            raise ValueError("target_id, room_id or composite_id is required")
        return target_type, target_id


class BookingUpdateRequest(BookingUpdate, WriteEnvelope):
    pass


class CancelBooking(BaseModel):
    reason: str = "会议取消"


class CancelBookingRequest(CancelBooking, WriteEnvelope):
    pass


class NLConfigureRequest(BaseModel):
    utterance: str
    workspace_id: str = "default"
    actor_id: str
    dry_run: bool = False
    idempotency_key: str
    expected_state_revision: int


class NLCandidatesRequest(BaseModel):
    utterance: str
    workspace_id: str = "default"
    actor_id: str
    dry_run: bool = True
    idempotency_key: str
    expected_state_revision: int


class FloorPlanRequest(BaseModel):
    floor_id: str | None = None
    date: str | None = None
    time: str | None = None
    include_status: bool = True
    include_rules: bool = True
    include_bookings: bool = True

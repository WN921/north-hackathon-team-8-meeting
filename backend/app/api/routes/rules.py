"""Rule, NL and floor-plan routes for RFC-0002."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, RepositoryDep
from app.core.config import DEFAULT_TIMEZONE, ErrorCode, now_iso, request_id
from app.domain.models import TimeWindow
from app.schemas.api import ApiMeta, NLConfigureRequest, NLCandidatesRequest, RuleCreateRequest, RuleDeleteRequest, RulePatchRequest, SuccessResponse
from app.services.api_service import APIError, check_idempotency, create_rule_from_parsed, floor_plan, parse_nl_candidates, parse_nl_configure, preview_rule_from_parsed, save_idempotency, validate_state_revision, list_available_targets

router = APIRouter(prefix="/api", tags=["Rules", "NaturalLanguage", "FloorPlan"])


def _meta(repository: RepositoryDep, revision: int | None = None) -> ApiMeta:
    return ApiMeta(state_revision=revision if revision is not None else repository.get_state_revision(), server_time=now_iso(), timezone=DEFAULT_TIMEZONE)


@router.get("/rules", response_model=SuccessResponse)
def list_rules(
    repository: RepositoryDep,
    _: CurrentUserDep,
    target_type: str | None = None,
    target_id: str | None = None,
    rule_type: str | None = None,
    fixed: bool | None = None,
    date: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> SuccessResponse:
    rules = repository.list_rules(target_type=target_type, target_id=target_id, rule_type=rule_type, fixed=fixed, date=date, limit=limit)
    return SuccessResponse(ok=True, request_id=request_id("req_rules"), data={"items": [rule.to_dict() for rule in rules]}, meta=_meta(repository))


@router.get("/rules/{rule_id}", response_model=SuccessResponse)
def get_rule(rule_id: str, repository: RepositoryDep, _: CurrentUserDep) -> SuccessResponse:
    rule = repository.get_rule(rule_id)
    if rule is None:
        raise APIError(ErrorCode.RULE_NOT_FOUND, "规则不存在", {"rule_id": rule_id}, ["请检查规则 ID"], 404)
    return SuccessResponse(ok=True, request_id=request_id("req_rule_detail"), data=rule.to_dict(), meta=_meta(repository))


@router.post("/rules", response_model=SuccessResponse)
def create_rule(payload: RuleCreateRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    try:
        existing = repository.match_rule(payload.target_type, payload.target_id, payload.rule_type, payload.match_key)
    except ValueError as exc:
        raise APIError(ErrorCode.IDEMPOTENCY_KEY_REUSED, str(exc), {}, ["请使用新的 idempotency_key 或提交相同请求"], 409) from exc
    rule_id = payload.rule_id or existing.id if existing else f"rule_{payload.target_id}_{payload.rule_type}"
    if existing and existing.fixed:
        raise APIError(ErrorCode.PROTECTED_RULE, "固定规则不可修改", {"rule_id": existing.id}, ["固定规则不可覆盖"], 409)
    old, new = create_rule_from_parsed(
        repository,
        {
            "parsed_changes": [
                {
                    "operation": "upsert_rule",
                    "target_type": payload.target_type,
                    "target_id": payload.target_id,
                    "rule_type": payload.rule_type,
                    "time_windows": [window.model_dump() for window in payload.time_windows],
                    "reason": payload.reason,
                }
            ],
            "matched_rule_id": existing.id if existing else None,
            "rule_id": rule_id,
            "match_key": payload.match_key,
        },
        user.id,
        dry_run=payload.dry_run,
    )
    revision = repository.get_state_revision() if payload.dry_run else repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_rule_upsert"), data={"rule_id": new.id, "matched_rule_id": existing.id if existing else None, "status": "updated" if old else "created", "old_rule": old.to_dict() if old else {}, "new_rule": new.to_dict(), "impacted_slots": [], "dry_run": payload.dry_run}, meta=_meta(repository, revision))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.patch("/rules/{rule_id}", response_model=SuccessResponse)
def patch_rule(rule_id: str, payload: RulePatchRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    old = repository.get_rule(rule_id)
    if old is None:
        raise APIError(ErrorCode.RULE_NOT_FOUND, "规则不存在", {"rule_id": rule_id}, ["请检查规则 ID"], 404)
    if old.fixed:
        raise APIError(ErrorCode.PROTECTED_RULE, "固定规则不可修改", {"rule_id": rule_id}, ["固定规则不可覆盖"], 409)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    updated = replace(old)
    if payload.time_windows:
        updated.time_windows = [TimeWindow(**window.model_dump()) for window in payload.time_windows]
    if payload.rule_type:
        updated.rule_type = payload.rule_type
    if payload.target_type:
        updated.target_type = payload.target_type
    if payload.target_id:
        updated.target_id = payload.target_id
    if payload.reason:
        updated.reason = payload.reason
    if payload.match_key:
        updated.match_key = payload.match_key
    updated.updated_by = user.id
    revision = repository.get_state_revision(payload.workspace_id) if payload.dry_run else repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_rule_update"), data={"rule_id": updated.id, "matched_rule_id": rule_id, "status": "updated", "old_rule": old.to_dict(), "new_rule": updated.to_dict(), "impacted_slots": [], "dry_run": payload.dry_run}, meta=_meta(repository, revision))
    if payload.dry_run:
        return response
    old_rule, new_rule = repository.upsert_rule(updated)
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.delete("/rules/{rule_id}", response_model=SuccessResponse)
def delete_rule(rule_id: str, payload: RuleDeleteRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    rule = repository.get_rule(rule_id)
    if rule is None:
        raise APIError(ErrorCode.RULE_NOT_FOUND, "规则不存在", {"rule_id": rule_id}, ["请检查规则 ID"], 404)
    if rule.fixed:
        raise APIError(ErrorCode.PROTECTED_RULE, "固定规则不可删除", {"rule_id": rule_id}, ["固定规则不可删除"], 409)
    revision = repository.get_state_revision() if payload.dry_run else repository.increment_state_revision(payload.workspace_id)
    if payload.dry_run:
        response = SuccessResponse(ok=True, request_id=request_id("req_rule_delete"), data={"rule_id": rule.id, "deleted": False, "dry_run": True}, meta=_meta(repository, revision))
        save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
        return response
    repository.delete_rule(rule_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_rule_delete"), data={"rule_id": rule.id, "deleted": True, "dry_run": False}, meta=_meta(repository, revision))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.post("/nl/configure", response_model=SuccessResponse)
def nl_configure(payload: NLConfigureRequest, repository: RepositoryDep, user: CurrentUserDep) -> SuccessResponse:
    cached = check_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json())
    if cached is not None:
        return SuccessResponse(**cached)
    validate_state_revision(repository, payload.expected_state_revision, payload.workspace_id)
    parsed = parse_nl_configure(payload.utterance, repository)
    old, new = create_rule_from_parsed(repository, parsed, user.id, dry_run=payload.dry_run)
    revision = repository.get_state_revision() if payload.dry_run else repository.increment_state_revision(payload.workspace_id)
    response = SuccessResponse(ok=True, request_id=request_id("req_nl_configure"), data={"intent": parsed["intent"], "llm": parsed["llm"], "parsed_changes": parsed["parsed_changes"], "matched_rule_id": parsed.get("matched_rule_id") or (old.id if old else None), "rule_id": new.id, "status": "updated" if old else "created", "old_rule": old.to_dict() if old else {}, "new_rule": new.to_dict(), "impacted_slots": [], "dry_run": payload.dry_run}, meta=_meta(repository, revision))
    save_idempotency(repository, payload.workspace_id, user.id, payload.idempotency_key, payload.model_dump_json(), response.model_dump())
    return response


@router.post("/nl/bookings:candidates", response_model=SuccessResponse)
def nl_candidates(payload: NLCandidatesRequest, repository: RepositoryDep, _: CurrentUserDep) -> SuccessResponse:
    parsed = parse_nl_candidates(payload.utterance)
    data = list_available_targets(repository, parsed["parsed_booking"]["start_at"], parsed["parsed_booking"]["end_at"], room_types=[parsed["parsed_booking"]["room_type"]], allow_merge=True)
    candidates = [{"target_type": item["target_type"], "target_id": item["target_id"], "name": item["name"], "available": item["available"]} for item in data["available_targets"]]
    excluded = data["unavailable_targets"]
    response = SuccessResponse(ok=True, request_id=request_id("req_nl_candidates"), data={"intent": parsed["intent"], "llm": parsed["llm"], "parsed_booking": parsed["parsed_booking"], "candidates": candidates, "excluded_targets": excluded}, meta=_meta(repository))
    return response


@router.get("/floor-plan", response_model=SuccessResponse)
def get_floor_plan(repository: RepositoryDep, _: CurrentUserDep, floor_id: str | None = None, date: str | None = None, time: str | None = None, include_status: bool = True, include_rules: bool = True, include_bookings: bool = True) -> SuccessResponse:
    return SuccessResponse(ok=True, request_id=request_id("req_floor_plan"), data=floor_plan(repository, floor_id or "5F", date, time, include_status, include_rules, include_bookings), meta=_meta(repository))

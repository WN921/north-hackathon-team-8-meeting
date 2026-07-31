"""FastAPI app entrypoint and route registration. RFC-0002."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import current_user, get_repository, require_bearer_token
from app.api.routes import auth, bookings, calendar, rooms, rules
from app.core.config import DEFAULT_TIMEZONE, ErrorCode, expected_llm_config, llm_runtime_config, now_iso, request_id
from app.repositories.meeting import MeetingRepository, db_session
from app.services.api_service import APIError

app = FastAPI(
    title="Meeting Room Booking API",
    description="本地会务系统 FastAPI 后端 API。RFC-0002 定义完整 API 契约。",
    version="0.1.0",
    openapi_tags=[
        {"name": "Auth", "description": "本地账号密码登录与当前用户"},
        {"name": "Rooms", "description": "会议室与开放时段配置"},
        {"name": "Availability", "description": "可用会议室查询与冲突预检"},
        {"name": "Rules", "description": "规则管理与自然语言配置"},
        {"name": "NaturalLanguage", "description": "自然语言配置与预约候选"},
        {"name": "Bookings", "description": "预约创建、取消、修改、列表和详情"},
        {"name": "Calendar", "description": "日历与时段占用"},
        {"name": "FloorPlan", "description": "平面图状态"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    with db_session() as conn:
        repository = MeetingRepository(conn)
        repository.init_schema()
        repository.seed_defaults()


def _meta(revision: int = 0) -> dict[str, object]:
    return {"state_revision": revision, "server_time": now_iso(), "timezone": DEFAULT_TIMEZONE}


@app.exception_handler(APIError)
async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    revision = 0
    try:
        with get_repository() as repository:
            revision = repository.get_state_revision()
    except Exception:
        pass
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "request_id": request_id(), "error": {"code": exc.error_code, "message": exc.detail["message"], "details": exc.error_details, "suggestions": exc.error_suggestions}, "warnings": [], "meta": _meta(revision)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"ok": False, "request_id": request_id(), "error": {"code": ErrorCode.VALIDATION_ERROR, "message": "入参格式或字段错误", "details": {"errors": exc.errors()}, "suggestions": ["请检查请求字段类型、必填字段和枚举值"]}, "warnings": [], "meta": _meta()})


@app.exception_handler(Exception)
async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 500)
    if status_code == 401:
        code = ErrorCode.UNAUTHORIZED
        message = "未登录或 token 无效"
    elif status_code == 403:
        code = ErrorCode.FORBIDDEN
        message = "当前用户无权执行"
    else:
        code = ErrorCode.VALIDATION_ERROR if status_code < 500 else ErrorCode.INTERNAL_SERVER_ERROR
        message = str(exc) or "请求处理失败"
    return JSONResponse(status_code=status_code, content={"ok": False, "request_id": request_id(), "error": {"code": code, "message": message, "details": {}, "suggestions": []}, "warnings": [], "meta": _meta()})


@app.get("/api/health")
def health() -> dict[str, object]:
    repository = MeetingRepository()
    repository.init_schema()
    repository.seed_defaults()
    revision = repository.get_state_revision()
    repository.close()
    llm = llm_runtime_config()
    expected = expected_llm_config()
    provider_ok = llm["provider"] == expected["provider"]
    model_ok = llm["model"] == expected["model"]
    api_key_ok = bool(llm["api_key_present"])
    return {"ok": True, "request_id": request_id("req_health"), "data": {"status": "ok", "sqlite": "available", "llm": {"provider": llm["provider"], "model": llm["model"], "api_key_present": api_key_ok, "configured": provider_ok and model_ok and api_key_ok}, "external_systems": {"calendar": "disabled", "payment": "disabled", "restaurant": "disabled", "external_meeting_rooms": "disabled"}}, "warnings": [] if provider_ok and model_ok and api_key_ok else ["LLM_PROVIDER、LLM_MODEL 或 NEX_AGI_API_KEY 未完全配置"], "meta": _meta(revision)}


app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(rules.router)
app.include_router(bookings.router)
app.include_router(calendar.router)

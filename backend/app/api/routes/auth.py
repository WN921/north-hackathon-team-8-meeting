"""Auth routes implementing RFC-0002 login, logout and current user contract."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, RepositoryDep
from app.auth.local import authenticate_user, issue_token
from app.core.config import ErrorCode, now_iso, request_id
from app.schemas.api import ApiMeta, ErrorResponse, LoginRequest, LoginResponseData, SuccessResponse, UserOut
from app.services.api_service import APIError

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=SuccessResponse)
def login(payload: LoginRequest, repository: RepositoryDep) -> SuccessResponse:
    """Log in with the local demo account."""

    user = authenticate_user(repository, payload.username, payload.password)
    if user is None:
        raise APIError(ErrorCode.UNAUTHORIZED, "用户名或密码错误", {}, ["请检查演示账号和密码"], 401)
    token = issue_token(user["id"])
    return SuccessResponse(
        ok=True,
        request_id=request_id("req_login"),
        data=LoginResponseData(user=UserOut(**user), token=token).model_dump(),
        warnings=[],
        meta=ApiMeta(state_revision=repository.get_state_revision(), server_time=now_iso(), timezone="Asia/Shanghai"),
    )


@router.post("/logout", response_model=SuccessResponse)
def logout(_: CurrentUserDep) -> SuccessResponse:
    return SuccessResponse(ok=True, request_id=request_id("req_logout"), data={"logged_out": True}, meta=ApiMeta(state_revision=0, server_time=now_iso(), timezone="Asia/Shanghai"))


@router.get("/me", response_model=SuccessResponse)
def me(user: CurrentUserDep) -> SuccessResponse:
    return SuccessResponse(ok=True, request_id=request_id("req_me"), data={"user": user}, meta=ApiMeta(state_revision=0, server_time=now_iso(), timezone="Asia/Shanghai"))

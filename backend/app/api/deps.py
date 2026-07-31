"""API dependency injection for FastAPI routes. RFC-0002."""

from __future__ import annotations

from typing import Annotated, Generator

from fastapi import Depends, Header

from app.auth.local import TOKEN_PREFIX
from app.core.config import ErrorCode
from app.repositories.meeting import MeetingRepository, db_session
from app.schemas.api import UserOut
from app.services.api_service import APIError


def get_repository() -> Generator[MeetingRepository, None, None]:
    with db_session() as conn:
        repository = MeetingRepository(conn)
        repository.init_schema()
        repository.seed_defaults()
        yield repository


def require_bearer_token(authorization: Annotated[str | None, Header(alias="Authorization")] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise APIError(ErrorCode.UNAUTHORIZED, "未登录或 token 无效", {}, ["请在 Authorization Header 中传入 Bearer token"], 401)
    token = authorization.removeprefix("Bearer ").strip()
    if not token.startswith(TOKEN_PREFIX):
        raise APIError(ErrorCode.UNAUTHORIZED, "未登录或 token 无效", {}, ["请检查本地演示 token"], 401)
    return token


def current_user(token: Annotated[str, Depends(require_bearer_token)]) -> UserOut:
    user_id = token.split("-", 2)[1] if "-" in token else token
    return UserOut(id=user_id, name="演示用户", role="member")


RepositoryDep = Annotated[MeetingRepository, Depends(get_repository)]
CurrentUserDep = Annotated[UserOut, Depends(current_user)]

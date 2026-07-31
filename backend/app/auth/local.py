"""Local authentication helpers for the demo backend. RFC-0002."""

from __future__ import annotations

import hashlib
import secrets

from app.repositories.meeting import MeetingRepository

TOKEN_PREFIX = "local-demo-token"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(stored_hash: str, password: str) -> bool:
    return secrets.compare_digest(stored_hash, hash_password(password))


def authenticate_user(repository: MeetingRepository, username: str, password: str) -> dict[str, str] | None:
    row = repository.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None or not verify_password(row["password"], password):
        return None
    return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"]}


def issue_token(user_id: str) -> str:
    return f"{TOKEN_PREFIX}-{user_id}-{secrets.token_urlsafe(12)}"

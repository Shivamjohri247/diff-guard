from __future__ import annotations

from redis_cache import get_redis
from utils.validators import validate_email


def create_session(username: str) -> str:
    return f"session-{username}"


def destroy_session(session_id: str) -> None:
    pass


def validate_session(session_id: str) -> bool:
    return bool(session_id)

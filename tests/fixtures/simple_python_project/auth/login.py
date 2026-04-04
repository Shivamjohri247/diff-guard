from __future__ import annotations

from auth.session import create_session
from utils.validators import validate_email


def login(username: str, password: str) -> str:
    session = create_session(username)
    return session


def authenticate(token: str) -> bool:
    return bool(token)

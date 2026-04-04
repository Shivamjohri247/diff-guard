from __future__ import annotations

from auth.session import create_session, validate_session


def test_auth_flow() -> None:
    session = create_session("user")
    assert session
    assert validate_session(session)


def test_session_creation() -> None:
    session = create_session("admin")
    assert "session-" in session

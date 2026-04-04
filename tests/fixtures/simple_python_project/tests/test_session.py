from __future__ import annotations

from auth.session import create_session


def test_create_session() -> None:
    session = create_session("user")
    assert session.startswith("session-")

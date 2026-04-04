from __future__ import annotations

from auth.login import login


def test_login_in_auth_dir() -> None:
    result = login("user", "pass")
    assert result.startswith("session-")

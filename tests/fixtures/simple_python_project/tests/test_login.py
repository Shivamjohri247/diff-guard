from __future__ import annotations

from auth.login import login, authenticate
from utils.validators import validate_email


def test_login() -> None:
    result = login("user", "pass")
    assert result.startswith("session-")


def test_authenticate() -> None:
    assert authenticate("token") is True


def test_validate_email() -> None:
    assert validate_email("a@b.com") is True
    assert validate_email("invalid") is False

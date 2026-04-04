from __future__ import annotations

from utils.helpers import format_response


def test_format_response() -> None:
    result = format_response({"key": "value"})
    assert "key" in result

from __future__ import annotations

"""Utility helpers for diff-guard."""


def format_file_path(path: str, max_width: int = 60) -> str:
    """Truncate a file path to fit within max_width."""
    if len(path) <= max_width:
        return path
    return "..." + path[-(max_width - 3):]


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """Return singular or plural form based on count."""
    if count == 1:
        return singular
    return plural or singular + "s"

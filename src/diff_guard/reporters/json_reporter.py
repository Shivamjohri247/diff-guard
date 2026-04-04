from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from typing import Any

from diff_guard.models import BlastRadiusReport


def _to_serializable(obj: Any) -> Any:
    """Recursively convert dataclasses, sets, and enums to JSON-safe types."""
    if is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, Any] = {}
        for f in fields(obj):
            value = getattr(obj, f.name)
            result[f.name] = _to_serializable(value)
        return result
    if isinstance(obj, set):
        return sorted(_to_serializable(item) for item in obj)
    if isinstance(obj, list):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [_to_serializable(item) for item in obj]
    if hasattr(obj, "value"):
        # Enum
        return obj.value
    return obj


class JSONReporter:
    """Machine-readable JSON output."""

    def render_report(self, report: BlastRadiusReport) -> str:
        """Serialize BlastRadiusReport to pretty-printed JSON string."""
        data = _to_serializable(report)
        return json.dumps(data, indent=2, sort_keys=False)

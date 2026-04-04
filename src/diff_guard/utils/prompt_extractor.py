from __future__ import annotations

from pathlib import Path

from diff_guard.models import ScopeConfig


def find_prompt_file(repo_root: Path, config: ScopeConfig | None = None) -> Path | None:
    """Find the first existing prompt file in repo root."""
    cfg = config or ScopeConfig()
    for name in cfg.prompt_files:
        candidate = repo_root / name
        if candidate.is_file():
            return candidate
    return None


def read_prompt_file(path: Path) -> str:
    """Read and return prompt file contents. Returns empty string on error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

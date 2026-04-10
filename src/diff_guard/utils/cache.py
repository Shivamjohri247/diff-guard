"""Disk-based cache for FileGraph with mtime-based invalidation.

Stores the import dependency graph as JSON under ``.diff-guard-cache/graph.json``
in the repository root.  The cache is invalidated when any source file's mtime
changes or files are added/removed.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

# Directories to skip — must match FileGraph's set.
_SKIP_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".git", "node_modules", ".tox", ".eggs", "venv", ".venv", "site-packages"}
)

# Bump this when the cache format changes to force a full rebuild.
_CACHE_VERSION: int = 1

CACHE_DIR_NAME = ".diff-guard-cache"
CACHE_FILE_NAME = "graph.json"


@dataclass
class CacheEntry:
    """Serialized form of a FileGraph."""

    forward: dict[str, list[str]]
    reverse: dict[str, list[str]]
    file_mtimes: dict[str, float]
    version: int = _CACHE_VERSION


def cache_path(repo_root: Path) -> Path:
    """Return the cache file path for the given repo."""
    return repo_root.resolve() / CACHE_DIR_NAME / CACHE_FILE_NAME


def load_cache(path: Path) -> CacheEntry | None:
    """Load a cache entry from disk.  Returns ``None`` on any error."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    version = data.get("version", 0)
    if version != _CACHE_VERSION:
        return None

    forward = data.get("forward", {})
    reverse = data.get("reverse", {})
    mtimes = data.get("file_mtimes", {})

    # Validate types
    if (
        not isinstance(forward, dict)
        or not isinstance(reverse, dict)
        or not isinstance(mtimes, dict)
    ):
        return None

    return CacheEntry(
        forward={k: list(v) for k, v in forward.items()},
        reverse={k: list(v) for k, v in reverse.items()},
        file_mtimes={k: float(v) for k, v in mtimes.items()},
        version=version,
    )


def save_cache(
    path: Path,
    forward: dict[str, set[str]],
    reverse: dict[str, set[str]],
    mtimes: dict[str, float],
) -> None:
    """Persist the graph and mtimes to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _CACHE_VERSION,
        "forward": {k: sorted(v) for k, v in forward.items()},
        "reverse": {k: sorted(v) for k, v in reverse.items()},
        "file_mtimes": mtimes,
    }
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # Silently ignore write failures — caching is best-effort.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def collect_mtimes(repo_root: Path, file_paths: list[str]) -> dict[str, float]:
    """Collect mtimes for the given relative paths under *repo_root*."""
    mtimes: dict[str, float] = {}
    resolved = repo_root.resolve()
    for rel in file_paths:
        abs_path = resolved / rel
        with contextlib.suppress(OSError):
            mtimes[rel] = abs_path.stat().st_mtime
    return mtimes


def discover_source_files(repo_root: Path) -> set[str]:
    """Return the set of relative paths for all source files under *repo_root*."""
    from diff_guard.utils.file_graph import _EXTRA_SOURCE_EXTENSIONS

    resolved = repo_root.resolve()
    result: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        # Also skip the cache directory itself
        dirnames[:] = [d for d in dirnames if d != CACHE_DIR_NAME]
        for fname in filenames:
            suffix = Path(fname).suffix.lower()
            if suffix == ".py" or suffix in _EXTRA_SOURCE_EXTENSIONS:
                abs_path = Path(dirpath) / fname
                rel = abs_path.relative_to(resolved).as_posix()
                result.add(rel)
    return result


def is_stale(entry: CacheEntry, repo_root: Path) -> bool:
    """Return ``True`` if the cache entry is stale relative to the current filesystem."""
    current_files = discover_source_files(repo_root)
    cached_files = set(entry.file_mtimes.keys())

    # File set changed (additions or removals)
    if current_files != cached_files:
        return True

    # Check mtimes
    resolved = repo_root.resolve()
    for rel, cached_mtime in entry.file_mtimes.items():
        try:
            current_mtime = (resolved / rel).stat().st_mtime
        except OSError:
            return True  # File disappeared
        if current_mtime != cached_mtime:
            return True

    return False

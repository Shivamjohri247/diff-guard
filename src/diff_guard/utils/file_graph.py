from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from diff_guard.analyzers.language_detector import detect_language, get_analyzer
from diff_guard.analyzers.python_analyzer import PythonASTAnalyzer

# Directories to skip when walking the project tree.
_SKIP_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".git", "node_modules", ".tox", ".eggs", "venv", ".venv", "site-packages"}
)

# Source file extensions to discover (beyond .py which is always included).
_EXTRA_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
    }
)


class FileGraph:
    """Directed graph of file dependencies (imports)."""

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()
        self._analyzer = PythonASTAnalyzer()
        # Forward edges: file -> files it imports
        self._forward: dict[str, set[str]] = {}
        # Reverse edges: file -> files that import it
        self._reverse: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Walk project files, analyze imports, build adjacency list."""
        self._forward.clear()
        self._reverse.clear()

        source_files = self._discover_source_files()
        # Cache analyzers by language to avoid re-creating per file
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        _analyzers: dict[str, PythonASTAnalyzer | GenericAnalyzer] = {}

        for abs_path in source_files:
            rel = self._normalize(abs_path)
            self._forward.setdefault(rel, set())

            try:
                source = abs_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            language = detect_language(rel)
            if language not in _analyzers:
                _analyzers[language] = get_analyzer(language)
            analyzer = _analyzers[language]

            imports = analyzer.extract_imports(source, rel)
            for imp in imports:
                resolved = analyzer.resolve_module_path(imp, self._root, source_file=rel)
                if resolved is None:
                    # Skip unresolved imports (stdlib, third-party, etc.)
                    continue
                dep = self._normalize(self._root / resolved)
                # Skip self-references
                if dep == rel:
                    continue
                # Skip if the resolved dep is not in our graph (e.g., node_modules)
                self._forward.setdefault(rel, set()).add(dep)
                self._reverse.setdefault(dep, set()).add(rel)

        # Ensure every known file has a reverse entry (even if nobody imports it)
        for file_path in self._forward:
            self._reverse.setdefault(file_path, set())

    def build_cached(self) -> None:
        """Build the graph, using a disk cache when possible.

        Falls back to a full :meth:`build` on cache miss or staleness.
        """
        from diff_guard.utils.cache import (
            cache_path,
            collect_mtimes,
            is_stale,
            load_cache,
            save_cache,
        )

        path = cache_path(self._root)

        # Try loading from cache
        entry = load_cache(path)
        if entry is not None and not is_stale(entry, self._root):
            self._forward = {k: set(v) for k, v in entry.forward.items()}
            self._reverse = {k: set(v) for k, v in entry.reverse.items()}
            return

        # Cache miss or stale — full build
        self.build()

        # Save to cache
        all_files = list(self._forward.keys())
        mtimes = collect_mtimes(self._root, all_files)
        save_cache(path, self._forward, self._reverse, mtimes)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def dependents(self, file_path: str) -> list[str]:
        """Return files that import from the given file (reverse edges)."""
        normalized = self._normalize(self._root / file_path)
        return sorted(self._reverse.get(normalized, set()))

    def dependencies(self, file_path: str) -> list[str]:
        """Return files that the given file imports (forward edges)."""
        normalized = self._normalize(self._root / file_path)
        return sorted(self._forward.get(normalized, set()))

    def distance(self, from_file: str, to_file: str) -> int:
        """BFS shortest-path distance. Returns -1 if unreachable."""
        src = self._normalize(self._root / from_file)
        dst = self._normalize(self._root / to_file)
        if src == dst:
            return 0
        if src not in self._forward:
            return -1

        visited: set[str] = {src}
        queue: deque[tuple[str, int]] = deque([(src, 0)])

        while queue:
            current, dist = queue.popleft()
            for neighbour in self._forward.get(current, set()):
                if neighbour == dst:
                    return dist + 1
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, dist + 1))
        return -1

    def files_within_hops(self, file_path: str, max_hops: int) -> set[str]:
        """Return all files reachable within *max_hops* from the given file."""
        src = self._normalize(self._root / file_path)
        if src not in self._forward:
            return set()

        result: set[str] = set()
        visited: set[str] = {src}
        queue: deque[tuple[str, int]] = deque([(src, 0)])

        while queue:
            current, dist = queue.popleft()
            if dist > max_hops:
                continue
            result.add(current)
            for neighbour in self._forward.get(current, set()):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, dist + 1))
        return result

    def centrality(self, file_path: str) -> int:
        """Number of files that depend on this file (in-degree)."""
        normalized = self._normalize(self._root / file_path)
        return len(self._reverse.get(normalized, set()))

    def top_central_files(self, n: int = 10) -> list[tuple[str, int]]:
        """Return the N most-depended-upon files."""
        scored = [(path, len(deps)) for path, deps in self._reverse.items() if len(deps) > 0]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:n]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_source_files(self) -> list[Path]:
        """Return absolute paths to all source files under *repo_root*."""
        result: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                suffix = Path(fname).suffix.lower()
                if suffix == ".py" or suffix in _EXTRA_SOURCE_EXTENSIONS:
                    result.append(Path(dirpath) / fname)
        return result

    def _normalize(self, path: Path) -> str:
        """Return *path* relative to repo_root using forward slashes."""
        try:
            rel = path.relative_to(self._root)
        except ValueError:
            # path is already relative
            rel = path
        return rel.as_posix()

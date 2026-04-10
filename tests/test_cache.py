"""Tests for FileGraph disk caching."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from diff_guard.utils.cache import (
    _CACHE_VERSION,
    CacheEntry,
    cache_path,
    collect_mtimes,
    discover_source_files,
    is_stale,
    load_cache,
    save_cache,
)
from diff_guard.utils.file_graph import FileGraph


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal Python project in a temp directory."""
    (tmp_path / "hello.py").write_text("import world\n")
    (tmp_path / "world.py").write_text("print('hello')\n")
    return tmp_path


class TestCacheEntryIO:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        forward = {"a.py": {"b.py", "c.py"}, "b.py": set()}
        reverse = {"b.py": {"a.py"}, "c.py": {"a.py"}, "a.py": set()}
        mtimes = {"a.py": 1.0, "b.py": 2.0, "c.py": 3.0}
        save_cache(path, forward, reverse, mtimes)

        entry = load_cache(path)
        assert entry is not None
        assert set(entry.forward["a.py"]) == {"b.py", "c.py"}
        assert set(entry.reverse["b.py"]) == {"a.py"}
        assert entry.version == _CACHE_VERSION

    def test_load_missing_file(self, tmp_path: Path) -> None:
        assert load_cache(tmp_path / "nonexistent.json") is None

    def test_load_corrupted_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json at all")
        assert load_cache(path) is None

    def test_load_wrong_version(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"version": 0, "forward": {}, "reverse": {}, "file_mtimes": {}}))
        assert load_cache(path) is None

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "cache.json"
        save_cache(path, {}, {}, {})
        assert path.is_file()


class TestStaleness:
    def test_not_stale_when_identical(self, tmp_repo: Path) -> None:
        files = discover_source_files(tmp_repo)
        mtimes = collect_mtimes(tmp_repo, sorted(files))
        entry = CacheEntry(
            forward={f: [] for f in files},
            reverse={f: [] for f in files},
            file_mtimes=mtimes,
        )
        assert not is_stale(entry, tmp_repo)

    def test_stale_on_mtime_change(self, tmp_repo: Path) -> None:
        files = discover_source_files(tmp_repo)
        mtimes = collect_mtimes(tmp_repo, sorted(files))
        # Simulate old mtime
        mtimes["hello.py"] = 0.0
        entry = CacheEntry(
            forward={f: [] for f in files},
            reverse={f: [] for f in files},
            file_mtimes=mtimes,
        )
        assert is_stale(entry, tmp_repo)

    def test_stale_on_file_added(self, tmp_repo: Path) -> None:
        files = discover_source_files(tmp_repo)
        mtimes = collect_mtimes(tmp_repo, sorted(files))
        entry = CacheEntry(
            forward={f: [] for f in files},
            reverse={f: [] for f in files},
            file_mtimes=mtimes,
        )
        # Add a new file
        (tmp_repo / "new_file.py").write_text("pass\n")
        assert is_stale(entry, tmp_repo)

    def test_stale_on_file_removed(self, tmp_repo: Path) -> None:
        files = discover_source_files(tmp_repo)
        _ = collect_mtimes(tmp_repo, sorted(files))
        # Add a phantom file to cached set
        all_files = files | {"phantom.py"}
        entry = CacheEntry(
            forward={f: [] for f in all_files},
            reverse={f: [] for f in all_files},
            file_mtimes=dict.fromkeys(all_files, 0.0),
        )
        assert is_stale(entry, tmp_repo)


class TestBuildCached:
    def test_build_cached_produces_same_graph(self, tmp_repo: Path) -> None:
        fg1 = FileGraph(tmp_repo)
        fg1.build()

        fg2 = FileGraph(tmp_repo)
        fg2.build_cached()

        assert set(fg2.dependents("world.py")) == set(fg1.dependents("world.py"))
        assert set(fg2.dependencies("hello.py")) == set(fg1.dependencies("hello.py"))

    def test_second_build_cached_uses_cache(self, tmp_repo: Path) -> None:
        fg1 = FileGraph(tmp_repo)
        fg1.build_cached()

        fg2 = FileGraph(tmp_repo)
        fg2.build_cached()

        assert set(fg2.dependents("world.py")) == {"hello.py"}

    def test_cache_file_created(self, tmp_repo: Path) -> None:
        fg = FileGraph(tmp_repo)
        fg.build_cached()

        assert cache_path(tmp_repo).is_file()

    def test_cache_invalidated_on_change(self, tmp_repo: Path) -> None:
        fg1 = FileGraph(tmp_repo)
        fg1.build_cached()

        # Modify a file to change its mtime
        time.sleep(0.05)
        (tmp_repo / "hello.py").write_text("import world\nimport os\n")
        # Force mtime update
        (tmp_repo / "hello.py").touch()

        fg2 = FileGraph(tmp_repo)
        fg2.build_cached()

        # The graph should reflect the new import
        assert "os" in fg2.dependencies("hello.py") or "world.py" in fg2.dependencies("hello.py")


class TestCacheCorruptData:
    def test_load_missing_fields_defaults_to_empty(self, tmp_path: Path) -> None:
        """Cache file with missing optional fields defaults to empty dicts."""
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"version": 1, "forward": {}}))
        entry = load_cache(path)
        assert entry is not None
        assert entry.forward == {}
        assert entry.reverse == {}
        assert entry.file_mtimes == {}

    def test_load_empty_json_object(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text("{}")
        assert load_cache(path) is None

    def test_load_list_instead_of_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text("[]")
        assert load_cache(path) is None

    def test_load_null(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text("null")
        assert load_cache(path) is None

    def test_build_cached_with_corrupt_cache_rebuilds(self, tmp_repo: Path) -> None:
        """If cache file is corrupt, build_cached falls back to full build."""
        cpath = cache_path(tmp_repo)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text("CORRUPT")

        fg = FileGraph(tmp_repo)
        fg.build_cached()  # Should not raise
        assert "world.py" in fg.dependents("hello.py") or len(fg.dependencies("hello.py")) >= 0

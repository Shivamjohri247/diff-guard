from __future__ import annotations

from pathlib import Path

from diff_guard.core.test_mapper import TestMapper
from diff_guard.models import Change, ChangeType, TestSuggestion

# ---------------------------------------------------------------------------
# Lightweight FileGraph stub for testing import-chain discovery
# ---------------------------------------------------------------------------


class _StubFileGraph:
    """Minimal stub that satisfies the FileGraph interface used by TestMapper."""

    def __init__(self, dep_map: dict[str, list[str]] | None = None) -> None:
        self._dep_map = dep_map or {}

    def dependencies(self, file_path: str) -> list[str]:
        return self._dep_map.get(file_path, [])

    def dependents(self, file_path: str) -> list[str]:
        results: list[str] = []
        for src, deps in self._dep_map.items():
            if file_path in deps:
                results.append(src)
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_change(
    file_path: str,
    *,
    change_type: ChangeType = ChangeType.MODIFIED,
    functions_modified: list[str] | None = None,
    is_deleted: bool = False,
) -> Change:
    return Change(
        file_path=file_path,
        change_type=change_type,
        hunks=[],
        added_lines=1,
        removed_lines=0,
        functions_modified=functions_modified or [],
        is_deleted=is_deleted,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDirectNameMatch:
    def test_finds_test_login_for_auth_login(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        results = mapper.find_test_files("auth/login.py")
        assert "tests/test_login.py" in results

    def test_finds_test_helpers_for_utils_helpers(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        results = mapper.find_test_files("utils/helpers.py")
        assert "tests/test_helpers.py" in results


class TestDirectoryMatch:
    def test_finds_nested_test_dir_match(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        results = mapper.find_test_files("auth/login.py")
        # tests/auth/test_login.py matches via directory structure
        assert "tests/auth/test_login.py" in results


class TestImportChainMatch:
    def test_finds_test_by_import(self, simple_python_project: Path) -> None:
        # test_auth_flow.py imports from auth/session
        dep_map: dict[str, list[str]] = {
            "tests/integration/test_auth_flow.py": ["auth/session.py"],
            "tests/test_login.py": ["auth/login.py"],
        }
        fg = _StubFileGraph(dep_map)
        mapper = TestMapper(simple_python_project, file_graph=fg)
        results = mapper.find_tests_by_import("auth/session.py")
        assert "tests/integration/test_auth_flow.py" in results

    def test_no_file_graph_returns_empty(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project, file_graph=None)
        results = mapper.find_tests_by_import("auth/session.py")
        assert results == []


class TestFunctionMatch:
    def test_finds_test_by_function_name(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        results = mapper.find_tests_by_function("login")
        # tests/test_login.py contains test_login,
        # tests/auth/test_login.py contains test_login_in_auth_dir
        assert "tests/test_login.py" in results

    def test_no_match_returns_empty(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        results = mapper.find_tests_by_function("nonexistent_function_xyz")
        assert results == []


class TestDeduplication:
    def test_same_test_file_appears_once_with_highest_confidence(
        self, simple_python_project: Path
    ) -> None:
        mapper = TestMapper(simple_python_project)
        change = _make_change(
            "auth/login.py",
            functions_modified=["login"],
        )
        suggestions = mapper.map_changes_to_tests([change])

        # tests/test_login.py may be found via name match AND function match;
        # it should appear only once with the highest confidence
        login_suggestions = [s for s in suggestions if s.test_file == "tests/test_login.py"]
        assert len(login_suggestions) == 1
        assert login_suggestions[0].confidence >= 0.9


class TestNoTestsFound:
    def test_no_matching_tests(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        change = _make_change("api/unknown_endpoint.py")
        suggestions = mapper.map_changes_to_tests([change])
        assert suggestions == []

    def test_deleted_file_skipped(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        change = _make_change("auth/login.py", is_deleted=True)
        suggestions = mapper.map_changes_to_tests([change])
        assert suggestions == []


class TestSuggestCommand:
    def test_generates_pytest_command(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        suggestions = [
            TestSuggestion(
                test_file="tests/test_login.py",
                changed_file="auth/login.py",
                match_reason="direct name match",
                confidence=0.9,
            ),
            TestSuggestion(
                test_file="tests/test_helpers.py",
                changed_file="utils/helpers.py",
                match_reason="direct name match",
                confidence=0.9,
            ),
        ]
        cmd = mapper.suggest_test_command(suggestions)
        assert "pytest" in cmd
        assert "tests/test_helpers.py" in cmd
        assert "tests/test_login.py" in cmd
        assert "-v" in cmd

    def test_empty_suggestions(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        cmd = mapper.suggest_test_command([])
        assert cmd == ""

    def test_deduplicates_files_in_command(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        suggestions = [
            TestSuggestion(
                test_file="tests/test_login.py",
                changed_file="auth/login.py",
                match_reason="direct name match",
                confidence=0.9,
            ),
            TestSuggestion(
                test_file="tests/test_login.py",
                changed_file="auth/login.py",
                match_reason="function match: login",
                confidence=0.6,
            ),
        ]
        cmd = mapper.suggest_test_command(suggestions)
        # test_login.py should appear only once
        assert cmd.count("tests/test_login.py") == 1


class TestEmptyChanges:
    def test_empty_changes_returns_empty(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        suggestions = mapper.map_changes_to_tests([])
        assert suggestions == []


class TestNormalizeModulePath:
    def test_normalizes_path(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        result = mapper._normalize_module_path("auth/login.py")
        assert result == "auth.login"

    def test_top_level_file(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        result = mapper._normalize_module_path("main.py")
        assert result == "main"


class TestMapChangesIntegration:
    def test_multiple_changes_deduplicates_across_changes(
        self, simple_python_project: Path
    ) -> None:
        mapper = TestMapper(simple_python_project)
        changes = [
            _make_change("auth/login.py", functions_modified=["login"]),
            _make_change("auth/session.py"),
        ]
        suggestions = mapper.map_changes_to_tests(changes)
        test_files = {s.test_file for s in suggestions}
        # Each test file appears at most once
        assert len(test_files) == len(suggestions)

    def test_confidence_ordering(self, simple_python_project: Path) -> None:
        mapper = TestMapper(simple_python_project)
        change = _make_change("auth/login.py", functions_modified=["login"])
        suggestions = mapper.map_changes_to_tests([change])
        # At least one suggestion should have confidence >= 0.9
        assert any(s.confidence >= 0.9 for s in suggestions)

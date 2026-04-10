from __future__ import annotations

from pathlib import Path

import pytest

from diff_guard.utils.file_graph import FileGraph


class TestBuildGraph:
    """Verify that the graph builds correctly from the fixture project."""

    def test_build_graph(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # The graph should have discovered multiple Python files
        assert len(graph._forward) > 0

        # app.py should depend on several files
        deps = graph.dependencies("app.py")
        assert "auth/login.py" in deps
        assert "auth/session.py" in deps
        assert "payments/stripe.py" in deps
        assert "api/dashboard.py" in deps

    def test_dependents(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        dependents = graph.dependents("auth/session.py")
        # auth/session.py is imported by: app.py, auth/login.py, api/users.py,
        # api/dashboard.py, payments/stripe.py, tests/test_session.py,
        # tests/integration/test_auth_flow.py
        assert "api/users.py" in dependents
        assert "api/dashboard.py" in dependents
        assert "payments/stripe.py" in dependents
        assert "auth/login.py" in dependents

    def test_dependencies(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        deps = graph.dependencies("auth/login.py")
        # auth/login.py imports auth.session
        assert "auth/session.py" in deps

    def test_distance_direct(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # auth/login.py -> auth/session.py (direct edge) = 1
        assert graph.distance("auth/login.py", "auth/session.py") == 1

    def test_distance_two_hops(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # app.py directly imports auth/session.py
        assert graph.distance("app.py", "auth/session.py") == 1

        # app.py -> auth/session.py -> redis_cache.py = 2 hops
        assert graph.distance("app.py", "redis_cache.py") == 2

        # app.py -> api/dashboard.py -> middleware/rate_limit.py -> redis_cache.py = 3
        # (but shorter path exists via auth/session, so distance is 2)
        # Verify the longer path by checking api/dashboard -> redis_cache = 2
        assert graph.distance("api/dashboard.py", "redis_cache.py") == 2

    def test_distance_same_file(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        assert graph.distance("app.py", "app.py") == 0

    def test_distance_unreachable(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # utils/validators.py has no outgoing imports, so it can't reach anything
        assert graph.distance("utils/validators.py", "app.py") == -1

    def test_files_within_hops(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # Within 1 hop of app.py: itself + its direct dependencies
        within_1 = graph.files_within_hops("app.py", 1)
        assert "app.py" in within_1
        assert "auth/login.py" in within_1
        assert "auth/session.py" in within_1

        # Within 2 hops should include redis_cache (reachable via auth/session)
        within_2 = graph.files_within_hops("app.py", 2)
        assert "redis_cache.py" in within_2
        assert len(within_2) > len(within_1)

    def test_files_within_hops_includes_self(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        within_0 = graph.files_within_hops("app.py", 0)
        assert within_0 == {"app.py"}

    def test_centrality(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # auth/session.py should have high centrality (many files import it)
        session_central = graph.centrality("auth/session.py")
        assert session_central >= 4  # app, login, users, dashboard, stripe, ...

        # app.py should have zero centrality (nothing imports it)
        app_central = graph.centrality("app.py")
        assert app_central == 0

    def test_top_central_files(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        top = graph.top_central_files(n=3)
        assert len(top) > 0
        # Each entry is (file_path, count)
        for path, count in top:
            assert isinstance(path, str)
            assert isinstance(count, int)
            assert count > 0

        # auth/session.py should be among the top files
        top_paths = [p for p, _ in top]
        assert "auth/session.py" in top_paths

        # Results should be in descending order of centrality
        counts = [c for _, c in top]
        assert counts == sorted(counts, reverse=True)

    def test_unreachable_file(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # File not in the graph
        assert graph.dependents("nonexistent.py") == []
        assert graph.dependencies("nonexistent.py") == []
        assert graph.centrality("nonexistent.py") == 0
        assert graph.files_within_hops("nonexistent.py", 3) == set()

    def test_standalone_files_have_no_dependencies(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # utils/validators.py is standalone (no imports from the project)
        deps = graph.dependencies("utils/validators.py")
        assert deps == []


class TestMultiLanguageGraph:
    """Verify multi-language graph building with Python + JS/TS files."""

    @pytest.fixture
    def multi_lang_project(self, fixtures_dir: Path) -> Path:
        return fixtures_dir / "multi_language_project"

    def test_discovers_js_and_ts_files(self, multi_lang_project: Path) -> None:
        graph = FileGraph(multi_lang_project)
        graph.build()
        files = set(graph._forward.keys())
        assert "src/helpers.js" in files
        assert "src/app.js" in files
        assert "src/config.ts" in files
        assert "src/server.ts" in files

    def test_js_import_resolved(self, multi_lang_project: Path) -> None:
        graph = FileGraph(multi_lang_project)
        graph.build()
        deps = graph.dependencies("src/app.js")
        assert "src/helpers.js" in deps

    def test_ts_import_resolved(self, multi_lang_project: Path) -> None:
        graph = FileGraph(multi_lang_project)
        graph.build()
        deps = graph.dependencies("src/server.ts")
        assert "src/config.ts" in deps

    def test_js_dependents(self, multi_lang_project: Path) -> None:
        graph = FileGraph(multi_lang_project)
        graph.build()
        dependents = graph.dependents("src/helpers.js")
        assert "src/app.js" in dependents

    def test_python_graph_unchanged(self, multi_lang_project: Path) -> None:
        graph = FileGraph(multi_lang_project)
        graph.build()
        deps = graph.dependencies("src/main.py")
        assert "src/utils.py" in deps


class TestGenericAnalyzerResolve:
    """Test JS/TS module path resolution in GenericAnalyzer."""

    def test_resolve_relative_js_import(self, tmp_path: Path) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        (tmp_path / "helpers.js").write_text("export function add() {}")
        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("./helpers", tmp_path)
        assert result is not None
        assert result.replace("\\", "/") == "helpers.js"

    def test_resolve_relative_ts_import(self, tmp_path: Path) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        (tmp_path / "config.ts").write_text("export const x = 1;")
        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("./config", tmp_path)
        assert result is not None
        assert result.replace("\\", "/") == "config.ts"

    def test_resolve_index_file(self, tmp_path: Path) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        utils_dir = tmp_path / "utils"
        utils_dir.mkdir()
        (utils_dir / "index.js").write_text("export {}")
        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("./utils", tmp_path)
        assert result is not None
        assert "utils" in result and "index.js" in result

    def test_non_relative_import_returns_none(self, tmp_path: Path) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("react", tmp_path)
        assert result is None

    def test_resolve_exact_extension(self, tmp_path: Path) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        (tmp_path / "helpers.js").write_text("export {}")
        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("./helpers.js", tmp_path)
        assert result is not None

    def test_resolve_from_subdirectory(self, tmp_path: Path) -> None:
        """Relative import resolved from source file's directory, not project root."""
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.js").write_text("import {}")
        (src / "helpers.js").write_text("export {}")
        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("./helpers", tmp_path, source_file="src/app.js")
        assert result is not None
        assert "helpers.js" in result

    def test_resolve_outside_project_returns_none(self, tmp_path: Path) -> None:
        """Imports that resolve outside project root should return None."""
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.js").write_text("import {}")
        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("../../outside", tmp_path, source_file="src/app.js")
        assert result is None

    def test_resolve_nonexistent_file(self, tmp_path: Path) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        result = analyzer.resolve_module_path("./nonexistent", tmp_path)
        assert result is None


class TestGenericAnalyzerEdgeCases:
    """Edge case tests for the generic analyzer."""

    def test_extract_functions_empty_source(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        assert analyzer.extract_functions("") == []

    def test_extract_imports_unknown_language(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        # Unknown extension falls through to generic patterns
        result = analyzer.extract_imports("import foo.bar", "readme.txt")
        # Generic pattern should match "import foo.bar"
        assert "foo.bar" in result

    def test_extract_functions_python_syntax(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        source = "def hello():\n    pass\ndef world():\n    pass"
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(source)
        names = [f[0] for f in funcs]
        assert "hello" in names
        assert "world" in names

    def test_extract_functions_go_syntax(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        source = "func main() {\n}\nfunc (s *Server) handle() {\n}"
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(source)
        names = [f[0] for f in funcs]
        assert "main" in names
        assert "handle" in names

    def test_extract_classes_returns_empty(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        assert analyzer.extract_classes("class Foo") == []

    def test_extract_calls_returns_empty(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        assert analyzer.extract_calls("foo()") == []

    def test_line_to_function_empty_source(self) -> None:
        from diff_guard.analyzers.generic_analyzer import GenericAnalyzer

        analyzer = GenericAnalyzer()
        assert analyzer.line_to_function("", [1, 2]) == []

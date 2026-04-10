from __future__ import annotations

import warnings
from pathlib import Path

from diff_guard.analyzers.generic_analyzer import GenericAnalyzer
from diff_guard.analyzers.language_detector import detect_language, detect_languages, get_analyzer
from diff_guard.analyzers.python_analyzer import PythonASTAnalyzer


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("app.py") == "python"

    def test_python_pyw(self) -> None:
        assert detect_language("gui.pyw") == "python"

    def test_javascript(self) -> None:
        assert detect_language("app.js") == "javascript"

    def test_typescript(self) -> None:
        assert detect_language("app.ts") == "typescript"

    def test_tsx(self) -> None:
        assert detect_language("component.tsx") == "typescript"

    def test_go(self) -> None:
        assert detect_language("main.go") == "go"

    def test_rust(self) -> None:
        assert detect_language("lib.rs") == "rust"

    def test_java(self) -> None:
        assert detect_language("App.java") == "java"

    def test_ruby(self) -> None:
        assert detect_language("app.rb") == "ruby"

    def test_c(self) -> None:
        assert detect_language("main.c") == "c"

    def test_cpp(self) -> None:
        assert detect_language("app.cpp") == "cpp"

    def test_unknown_extension(self) -> None:
        assert detect_language("readme.txt") == "unknown"

    def test_no_extension(self) -> None:
        assert detect_language("Makefile") == "unknown"

    def test_case_insensitive(self) -> None:
        assert detect_language("App.PY") == "python"


class TestDetectLanguages:
    def test_ranked_by_frequency(self, tmp_path: Path) -> None:
        files = ["a.py", "b.py", "c.js", "d.py", "e.ts"]
        result = detect_languages(files, tmp_path)
        # python appears 3 times, javascript 1, typescript 1
        assert result[0] == "python"

    def test_excludes_unknown(self, tmp_path: Path) -> None:
        files = ["a.py", "readme.txt", "Makefile"]
        result = detect_languages(files, tmp_path)
        assert "unknown" not in result

    def test_empty_list(self, tmp_path: Path) -> None:
        assert detect_languages([], tmp_path) == []


class TestGetAnalyzer:
    def test_python_returns_ast_analyzer(self) -> None:
        analyzer = get_analyzer("python")
        assert isinstance(analyzer, PythonASTAnalyzer)

    def test_javascript_returns_generic_with_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            analyzer = get_analyzer("javascript")
            assert isinstance(analyzer, GenericAnalyzer)
            assert len(w) == 1
            assert "javascript" in str(w[0].message)

    def test_typescript_returns_generic_with_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            analyzer = get_analyzer("typescript")
            assert isinstance(analyzer, GenericAnalyzer)
            assert len(w) == 1

    def test_go_returns_generic(self) -> None:
        analyzer = get_analyzer("go")
        assert isinstance(analyzer, GenericAnalyzer)

    def test_unknown_returns_generic(self) -> None:
        analyzer = get_analyzer("cobol")
        assert isinstance(analyzer, GenericAnalyzer)

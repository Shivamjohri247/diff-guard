from __future__ import annotations

import warnings
from pathlib import Path
from tempfile import TemporaryDirectory

from diff_guard.analyzers.language_detector import (
    GenericAnalyzer,
    detect_language,
    detect_languages,
    get_analyzer,
)
from diff_guard.analyzers.python_analyzer import PythonASTAnalyzer, map_lines_to_functions

# ======================================================================
# Sample source code used across tests
# ======================================================================

SAMPLE_PY_SOURCE = """\
import os
import os.path
from pathlib import Path
from auth.login import authenticate
from collections import defaultdict

def helper(x: int) -> int:
    return x * 2

class UserService:
    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return f"Hello, {self.name}"

async def fetch_data(url: str) -> dict:
    import json
    return json.loads("{}")
"""

SYNTAX_ERROR_SOURCE = """\
def broken(
    # missing closing paren and colon
    x
"""

EMPTY_SOURCE = ""

RELATIVE_IMPORT_SOURCE = """\
from . import sibling
from ..parent import thing
from .child import nested_func
"""

CALLS_SOURCE = """\
import os

def run():
    result = process(data)
    os.path.join("a", "b")
    obj.method()
    outer.inner.deepest()
    print("hello")
"""


# ======================================================================
# Tests for PythonASTAnalyzer
# ======================================================================


class TestExtractImports:
    def test_extract_imports(self) -> None:
        analyzer = PythonASTAnalyzer()
        imports = analyzer.extract_imports(SAMPLE_PY_SOURCE, "example.py")
        assert "os" in imports
        assert "os.path" in imports
        assert "pathlib" in imports
        assert "auth.login" in imports
        assert "collections" in imports

    def test_extract_relative_imports(self) -> None:
        analyzer = PythonASTAnalyzer()
        imports = analyzer.extract_imports(RELATIVE_IMPORT_SOURCE, "relative.py")
        assert ".sibling" in imports
        assert "..parent.thing" in imports
        assert ".child.nested_func" in imports


class TestExtractFunctions:
    def test_extract_functions(self) -> None:
        analyzer = PythonASTAnalyzer()
        funcs = analyzer.extract_functions(SAMPLE_PY_SOURCE)
        names = [name for name, _, _ in funcs]
        # Top-level
        assert "helper" in names
        assert "fetch_data" in names
        # Methods
        assert "__init__" in names
        assert "greet" in names

    def test_function_line_ranges(self) -> None:
        analyzer = PythonASTAnalyzer()
        funcs = analyzer.extract_functions(SAMPLE_PY_SOURCE)
        by_name = {name: (start, end) for name, start, end in funcs}
        # helper is on line 7 of SAMPLE_PY_SOURCE (1-indexed)
        start, end = by_name["helper"]
        assert start == 7
        assert end == 8

    def test_nested_functions_included(self) -> None:
        source = """\
def outer():
    def inner():
        pass
    return inner
"""
        analyzer = PythonASTAnalyzer()
        funcs = analyzer.extract_functions(source)
        names = [name for name, _, _ in funcs]
        assert "outer" in names
        assert "inner" in names


class TestExtractClasses:
    def test_extract_classes(self) -> None:
        analyzer = PythonASTAnalyzer()
        classes = analyzer.extract_classes(SAMPLE_PY_SOURCE)
        names = [name for name, _, _ in classes]
        assert "UserService" in names

    def test_class_line_range(self) -> None:
        analyzer = PythonASTAnalyzer()
        classes = analyzer.extract_classes(SAMPLE_PY_SOURCE)
        by_name = {name: (start, end) for name, start, end in classes}
        start, end = by_name["UserService"]
        # class UserService starts at line 10 of SAMPLE_PY_SOURCE
        assert start == 10
        assert end >= 15

    def test_multiple_classes(self) -> None:
        source = """\
class Alpha:
    pass

class Beta:
    x = 1
"""
        analyzer = PythonASTAnalyzer()
        classes = analyzer.extract_classes(source)
        names = [name for name, _, _ in classes]
        assert "Alpha" in names
        assert "Beta" in names


class TestLineToFunction:
    def test_line_to_function(self) -> None:
        analyzer = PythonASTAnalyzer()
        # Line 8 is inside helper() in SAMPLE_PY_SOURCE
        result = analyzer.line_to_function(SAMPLE_PY_SOURCE, [8])
        assert "helper" in result

    def test_line_in_method(self) -> None:
        analyzer = PythonASTAnalyzer()
        # Line 14 is inside greet() method
        result = analyzer.line_to_function(SAMPLE_PY_SOURCE, [14])
        assert "greet" in result

    def test_line_in_class_body(self) -> None:
        analyzer = PythonASTAnalyzer()
        # Line 12 (self.name = name) is inside __init__ method (most specific scope)
        result = analyzer.line_to_function(SAMPLE_PY_SOURCE, [12])
        assert "__init__" in result

    def test_line_outside_function(self) -> None:
        analyzer = PythonASTAnalyzer()
        # Line 1 is an import, not inside any function
        result = analyzer.line_to_function(SAMPLE_PY_SOURCE, [1])
        assert result == []

    def test_multiple_lines(self) -> None:
        analyzer = PythonASTAnalyzer()
        # Lines 8 and 14 hit two different functions
        result = analyzer.line_to_function(SAMPLE_PY_SOURCE, [8, 14])
        assert "helper" in result
        assert "greet" in result


class TestExtractCalls:
    def test_extract_calls(self) -> None:
        analyzer = PythonASTAnalyzer()
        calls = analyzer.extract_calls(CALLS_SOURCE)
        assert "process" in calls
        assert "os.path.join" in calls
        assert "obj.method" in calls
        assert "outer.inner.deepest" in calls
        assert "print" in calls


class TestResolveModulePath:
    def test_resolve_direct_module(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create src/auth/login.py
            (root / "src" / "auth").mkdir(parents=True)
            (root / "src" / "auth" / "login.py").write_text("# module")
            analyzer = PythonASTAnalyzer()
            result = analyzer.resolve_module_path("auth.login", root)
            assert result == "src/auth/login.py"

    def test_resolve_flat_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create auth/login.py (no src/ prefix)
            (root / "auth").mkdir(parents=True)
            (root / "auth" / "login.py").write_text("# module")
            analyzer = PythonASTAnalyzer()
            result = analyzer.resolve_module_path("auth.login", root)
            assert result == "auth/login.py"

    def test_resolve_package_init(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create src/auth/login/__init__.py
            (root / "src" / "auth" / "login").mkdir(parents=True)
            (root / "src" / "auth" / "login" / "__init__.py").write_text("# pkg")
            analyzer = PythonASTAnalyzer()
            result = analyzer.resolve_module_path("auth.login", root)
            assert result == "src/auth/login/__init__.py"

    def test_resolve_nonexistent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            analyzer = PythonASTAnalyzer()
            result = analyzer.resolve_module_path("nonexistent.module", root)
            assert result is None


class TestSyntaxErrorHandling:
    def test_syntax_error_returns_empty(self) -> None:
        analyzer = PythonASTAnalyzer()
        assert analyzer.extract_imports(SYNTAX_ERROR_SOURCE, "bad.py") == []
        assert analyzer.extract_functions(SYNTAX_ERROR_SOURCE) == []
        assert analyzer.extract_classes(SYNTAX_ERROR_SOURCE) == []
        assert analyzer.line_to_function(SYNTAX_ERROR_SOURCE, [1]) == []
        assert analyzer.extract_calls(SYNTAX_ERROR_SOURCE) == []


class TestEmptySource:
    def test_empty_returns_empty(self) -> None:
        analyzer = PythonASTAnalyzer()
        assert analyzer.extract_imports(EMPTY_SOURCE, "empty.py") == []
        assert analyzer.extract_functions(EMPTY_SOURCE) == []
        assert analyzer.extract_classes(EMPTY_SOURCE) == []
        assert analyzer.line_to_function(EMPTY_SOURCE, []) == []
        assert analyzer.extract_calls(EMPTY_SOURCE) == []


class TestMapLinesToFunctions:
    def test_deduplication(self) -> None:
        # Lines 7 and 8 are both inside helper()
        result = map_lines_to_functions(SAMPLE_PY_SOURCE, [7, 8])
        assert result == ["helper"]

    def test_multiple_unique_functions(self) -> None:
        result = map_lines_to_functions(SAMPLE_PY_SOURCE, [8, 14])
        assert "helper" in result
        assert "greet" in result

    def test_no_matching_lines(self) -> None:
        result = map_lines_to_functions(SAMPLE_PY_SOURCE, [1])
        assert result == []


# ======================================================================
# Tests for language_detector
# ======================================================================


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("src/auth/login.py") == "python"

    def test_javascript(self) -> None:
        assert detect_language("src/app.js") == "javascript"

    def test_typescript(self) -> None:
        assert detect_language("src/app.ts") == "typescript"

    def test_unknown(self) -> None:
        assert detect_language("data.csv") == "unknown"


class TestDetectLanguages:
    def test_ranked_by_frequency(self) -> None:
        files = ["a.py", "b.py", "c.js", "d.ts"]
        result = detect_languages(files, Path("/tmp"))
        assert result[0] == "python"
        assert "javascript" in result
        assert "typescript" in result

    def test_excludes_unknown(self) -> None:
        files = ["a.py", "readme.md", "data.csv"]
        result = detect_languages(files, Path("/tmp"))
        assert "unknown" not in result
        assert result == ["python"]

    def test_empty_list(self) -> None:
        assert detect_languages([], Path("/tmp")) == []


class TestGetAnalyzer:
    def test_python_analyzer(self) -> None:
        analyzer = get_analyzer("python")
        assert isinstance(analyzer, PythonASTAnalyzer)

    def test_javascript_falls_back_with_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            analyzer = get_analyzer("javascript")
            assert isinstance(analyzer, GenericAnalyzer)
            assert len(w) == 1
            assert "tree-sitter" in str(w[0].message)

    def test_typescript_falls_back_with_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            analyzer = get_analyzer("typescript")
            assert isinstance(analyzer, GenericAnalyzer)
            assert len(w) == 1

    def test_unknown_language(self) -> None:
        analyzer = get_analyzer("rust")
        assert isinstance(analyzer, GenericAnalyzer)


class TestGenericAnalyzer:
    def test_generic_analyzer_interface(self) -> None:
        ga = GenericAnalyzer()
        # extract_imports is language-aware and returns results for known patterns
        assert "os" in ga.extract_imports("import os", "f.py")
        # extract_functions detects function definitions via regex
        funcs = ga.extract_functions("def f(): pass")
        assert len(funcs) == 1
        assert funcs[0][0] == "f"
        # Class / call extraction not supported by generic analyzer
        assert ga.extract_classes("class C: pass") == []
        assert ga.extract_calls("f()") == []
        # Module path resolution not supported by generic analyzer
        assert ga.resolve_module_path("os", Path("/tmp")) is None

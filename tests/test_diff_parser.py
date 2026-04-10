from __future__ import annotations

from pathlib import Path

from diff_guard.core.diff_parser import (
    _detect_modified_imports,
    _extract_function_from_header,
    detect_language,
    parse_unified_diff,
)
from diff_guard.models import ChangeType


class TestParseUnifiedDiff:
    def test_empty_diff(self) -> None:
        result = parse_unified_diff("")
        assert result == []

    def test_parse_clean_change(self, sample_diffs_dir: Path) -> None:
        diff_text = (sample_diffs_dir / "clean_change.diff").read_text()
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 1
        assert changes[0].file_path == "src/auth/login.py"
        assert changes[0].change_type == ChangeType.MODIFIED
        assert changes[0].added_lines == 5
        assert changes[0].removed_lines == 2
        assert changes[0].language == "python"

    def test_parse_butterfly_change(self, sample_diffs_dir: Path) -> None:
        diff_text = (sample_diffs_dir / "butterfly_change.diff").read_text()
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 3
        paths = [c.file_path for c in changes]
        assert "src/auth/login.py" in paths
        assert "src/auth/session.py" in paths
        assert "src/middleware/rate_limit.py" in paths

    def test_parse_new_file(self) -> None:
        diff_text = """diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,5 @@
+def hello():
+    return "world"
"""
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 1
        assert changes[0].is_new_file is True
        assert changes[0].change_type == ChangeType.ADDED

    def test_parse_deleted_file(self) -> None:
        diff_text = """diff --git a/src/old_module.py b/src/old_module.py
deleted file mode 100644
index 1234567..0000000
--- a/src/old_module.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def old_function():
-    pass
"""
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 1
        assert changes[0].is_deleted is True
        assert changes[0].removed_lines == 2

    def test_parse_renamed_file(self) -> None:
        diff_text = """diff --git a/src/old_name.py b/src/new_name.py
similarity index 95%
rename from src/old_name.py
rename to src/new_name.py
--- a/src/old_name.py
+++ b/src/new_name.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 2
"""
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.RENAMED
        assert changes[0].old_path == "src/old_name.py"

    def test_parse_multiple_hunks(self) -> None:
        diff_text = """diff --git a/src/auth/login.py b/src/auth/login.py
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -10,3 +10,4 @@ def validate_email(email):
     return True
+    return enhanced_validation(email)

@@ -30,3 +31,4 @@ def validate_password(password):
     return False
+    check_complexity(password)
"""
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 1
        assert len(changes[0].hunks) == 2

    def test_parse_config_side_effect(self, sample_diffs_dir: Path) -> None:
        diff_text = (sample_diffs_dir / "config_side_effect.diff").read_text()
        changes = parse_unified_diff(diff_text)
        assert len(changes) == 3
        paths = [c.file_path for c in changes]
        assert "src/auth/login.py" in paths
        assert "package-lock.json" in paths
        assert ".env.example" in paths

    def test_parse_binary_file(self) -> None:
        diff_text = """diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ
"""
        # Binary diffs don't have standard hunks, should handle gracefully
        changes = parse_unified_diff(diff_text)
        # May produce a change with no hunks or skip entirely
        assert isinstance(changes, list)


class TestExtractFunctionFromHeader:
    def test_python_def(self) -> None:
        result = _extract_function_from_header("def my_function")
        assert result == "my_function"

    def test_python_class(self) -> None:
        result = _extract_function_from_header("class MyClass")
        assert result == "MyClass"

    def test_empty_header(self) -> None:
        result = _extract_function_from_header("")
        assert result is None

    def test_no_prefix(self) -> None:
        result = _extract_function_from_header("some_function(")
        assert result == "some_function"


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("src/auth/login.py") == "python"

    def test_javascript(self) -> None:
        assert detect_language("src/app.js") == "javascript"

    def test_typescript(self) -> None:
        assert detect_language("src/app.ts") == "typescript"

    def test_unknown(self) -> None:
        assert detect_language("src/data.csv") == "unknown"


class TestDetectModifiedImports:
    def test_python_import_added(self) -> None:
        added = ["import os", "from pathlib import Path"]
        removed: list[str] = []
        result = _detect_modified_imports(added, removed)
        assert "os" in result
        assert "pathlib.Path" in result

    def test_js_import_added(self) -> None:
        added = ["import React from 'react'"]
        removed: list[str] = []
        result = _detect_modified_imports(added, removed)
        assert "react" in result or "React" in result

    def test_no_imports(self) -> None:
        added = ["x = 1", "def foo():"]
        removed: list[str] = []
        result = _detect_modified_imports(added, removed)
        assert result == []

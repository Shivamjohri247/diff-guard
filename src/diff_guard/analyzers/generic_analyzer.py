from __future__ import annotations

import re
from pathlib import Path


class GenericAnalyzer:
    """Grep-based fallback analyzer for any language.

    Provides the same public interface as :class:`PythonASTAnalyzer` but uses
    regex patterns instead of AST parsing.  Used for languages like Go, Rust,
    Java, Ruby, C/C++, JavaScript, TypeScript, etc.
    """

    # Directories to skip when scanning for references.
    _SKIP_DIRS: frozenset[str] = frozenset(
        {
            "__pycache__",
            ".git",
            "node_modules",
            ".tox",
            ".eggs",
            "venv",
            ".venv",
            "site-packages",
            "build",
            "dist",
            ".hg",
            ".svn",
            ".mypy_cache",
            ".pytest_cache",
        }
    )

    # ------------------------------------------------------------------
    # Import extraction
    # ------------------------------------------------------------------

    def extract_imports(self, source: str, file_path: str = "") -> list[str]:
        """Extract import/require/use statements using regex.

        Language-aware: detects file extension and uses appropriate patterns.
        """
        language = self._language_from_path(file_path)
        return self.detect_import_patterns(source, language)

    # ------------------------------------------------------------------
    # Function extraction
    # ------------------------------------------------------------------

    def extract_functions(self, source: str) -> list[tuple[str, int, int]]:
        """Extract function/method declarations using regex.

        Returns list of (name, start_line, end_line).
        For regex-based analysis *end_line* is set equal to *start_line*
        since we cannot determine the exact block extent without an AST.
        """
        results: list[tuple[str, int, int]] = []
        for line_no, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            # Generic function-like patterns
            for pattern in self._generic_function_patterns():
                m = pattern.match(stripped)
                if m:
                    name = m.group("name")
                    results.append((name, line_no, line_no))
                    break
        return results

    # ------------------------------------------------------------------
    # Class extraction (stub -- returns empty for generic analyzer)
    # ------------------------------------------------------------------

    def extract_classes(self, source: str) -> list[tuple[str, int, int]]:
        """Return empty list.  Class extraction is not regex-reliable."""
        return []

    # ------------------------------------------------------------------
    # Line-to-function mapping
    # ------------------------------------------------------------------

    def line_to_function(self, source: str, line_numbers: list[int]) -> list[str]:
        """Map *line_numbers* to their enclosing function names.

        Uses simple regex-based heuristics.  For languages where the block
        structure is hard to determine via regex, this returns empty.
        """
        funcs = self.extract_functions(source)
        if not funcs or not line_numbers:
            return []

        # Build line -> function mapping (best-effort: assign each line to
        # the nearest preceding function whose block *might* contain it).
        source_lines = source.splitlines()
        result: list[str] = []
        for target in line_numbers:
            best_name: str | None = None
            best_line = 0
            for name, start, _ in funcs:
                if start <= target and start > best_line:
                    best_name = name
                    best_line = start
            # Heuristic: assume function body extends to next function or EOF
            if best_name is not None:
                # Find the start of the next function after best_line
                next_func_line = len(source_lines) + 1
                for _, start2, _ in funcs:
                    if start2 > best_line and start2 < next_func_line:
                        next_func_line = start2
                if target <= next_func_line:
                    result.append(best_name)
        return result

    # ------------------------------------------------------------------
    # Call extraction (stub -- returns empty for generic analyzer)
    # ------------------------------------------------------------------

    def extract_calls(self, source: str) -> list[str]:
        """Return empty list.  Call extraction is not regex-reliable."""
        return []

    # ------------------------------------------------------------------
    # Module-path resolution (stub)
    # ------------------------------------------------------------------

    def resolve_module_path(
        self, import_path: str, project_root: Path, source_file: str = ""
    ) -> str | None:
        """Resolve an import path to a file path relative to project_root.

        Supports JavaScript/TypeScript relative imports.  Other languages
        return ``None`` (resolution is not yet implemented).
        """
        # JS/TS relative imports
        if import_path.startswith(".") or import_path.startswith("/"):
            return self._resolve_js_path(import_path, project_root, source_file)

        return None

    def _resolve_js_path(
        self, import_path: str, project_root: Path, source_file: str = ""
    ) -> str | None:
        """Resolve a JS/TS relative import path to a file."""
        resolved_root = project_root.resolve()

        # Resolve relative to the importing file's directory
        if source_file and import_path.startswith("."):
            source_dir = resolved_root / Path(source_file).parent
            abs_resolved = (source_dir / import_path).resolve()
            try:
                rel_resolved = abs_resolved.relative_to(resolved_root)
            except ValueError:
                return None
        else:
            abs_resolved = resolved_root / import_path
            rel_resolved = Path(import_path)

        # Try exact path
        if abs_resolved.is_file():
            return rel_resolved.as_posix()

        # Try with extensions
        for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            candidate = abs_resolved.with_suffix(ext)
            if candidate.is_file():
                return str(candidate.relative_to(resolved_root).as_posix())

        # Try index files in directory
        for ext in (".js", ".jsx", ".ts", ".tsx"):
            index = abs_resolved / f"index{ext}"
            if index.is_file():
                return str(index.relative_to(resolved_root).as_posix())

        return None

    # ------------------------------------------------------------------
    # Reference finding
    # ------------------------------------------------------------------

    def find_references(self, name: str, project_root: Path) -> list[str]:
        """Find all files that reference a given function/class name.

        Uses grep-like file scanning.  Excludes binary files and common
        non-source directories.
        """
        matches: list[str] = []
        # Build a word-boundary regex to avoid substring matches.
        ref_pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        for path in sorted(project_root.rglob("*")):
            if not path.is_file():
                continue
            # Skip excluded directories
            if any(part in self._SKIP_DIRS for part in path.parts):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError):
                # Binary file or unreadable -- skip
                continue
            if ref_pattern.search(content):
                rel = path.relative_to(project_root)
                matches.append(rel.as_posix())
        return matches

    # ------------------------------------------------------------------
    # Language-aware import detection
    # ------------------------------------------------------------------

    def detect_import_patterns(self, source: str, language: str) -> list[str]:
        """Language-aware import detection with regex patterns per language."""
        patterns = self._language_import_patterns(language)
        results: list[str] = []
        seen: set[str] = set()

        if language == "go":
            # Handle multi-line import blocks first
            results.extend(self._extract_go_multiline_imports(source, seen))

        for line in source.splitlines():
            stripped = line.strip()
            if (
                not stripped or stripped.startswith("//") or stripped.startswith("#")
            ) and language not in ("c", "cpp"):
                continue
            for pattern in patterns:
                m = pattern.search(stripped)
                if m:
                    import_text = m.group("path")
                    if import_text and import_text not in seen:
                        seen.add(import_text)
                        results.append(import_text)
                    break  # Only match one pattern per line
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _language_from_path(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext_map: dict[str, str] = {
            ".py": "python",
            ".pyw": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".c": "c",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
        }
        suffix = Path(file_path).suffix.lower() if file_path else ""
        return ext_map.get(suffix, "")

    def _language_import_patterns(self, language: str) -> list[re.Pattern[str]]:
        """Return regex patterns for import statements in a given language."""
        if language == "go":
            return self._go_import_patterns()
        if language == "rust":
            return self._rust_import_patterns()
        if language == "java":
            return self._java_import_patterns()
        if language == "ruby":
            return self._ruby_import_patterns()
        if language in ("c", "cpp"):
            return self._c_import_patterns()
        if language in ("javascript", "typescript"):
            return self._js_import_patterns()
        if language == "python":
            return self._python_import_patterns()
        # Generic fallback
        return self._generic_import_patterns()

    def _language_function_patterns(self, language: str) -> list[re.Pattern[str]]:
        """Return regex patterns for function declarations in a given language."""
        if language == "go":
            return self._go_function_patterns()
        if language == "rust":
            return self._rust_function_patterns()
        if language == "java":
            return self._java_function_patterns()
        if language == "ruby":
            return self._ruby_function_patterns()
        if language in ("javascript", "typescript"):
            return self._js_function_patterns()
        if language == "python":
            return self._python_function_patterns()
        # Generic fallback
        return self._generic_function_patterns()

    # ------------------------------------------------------------------
    # Per-language: import patterns
    # ------------------------------------------------------------------

    def _go_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r'^import\s+(?:"(?P<path>[^"]+)")'),
            re.compile(r'^import\s+\w+\s+"(?P<path>[^"]+)"'),
            # Single-line entries inside import ( ... ) are handled
            # by _extract_go_multiline_imports
            re.compile(r'^\s*"(?P<path>[^"]+)"\s*$'),
        ]

    def _rust_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"use\s+(?P<path>[\w:]+)"),
            re.compile(r"extern\s+crate\s+(?P<path>\w+)"),
        ]

    def _java_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"import\s+static\s+(?P<path>[\w.]+)"),
            re.compile(r"import\s+(?P<path>[\w.]+)\s*;"),
        ]

    def _ruby_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r'require_relative\s+"(?P<path>[^"]+)"'),
            re.compile(r"require_relative\s+'(?P<path>[^']+)'"),
            re.compile(r'require\s+"(?P<path>[^"]+)"'),
            re.compile(r"require\s+'(?P<path>[^']+)'"),
            re.compile(r"include\s+(?P<path>[\w:]+)"),
        ]

    def _c_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r'#include\s*"(?P<path>[^"]+)"'),
            re.compile(r"#include\s*<(?P<path>[^>]+)>"),
        ]

    def _js_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"""import\s+.*?\s+from\s+['"](?P<path>[^'"]+)['"]"""),
            re.compile(r"""export\s+.*?\s+from\s+['"](?P<path>[^'"]+)['"]"""),
            re.compile(r"""import\s+['"](?P<path>[^'"]+)['"]"""),
            re.compile(
                r"""(?:const|let|var)\s+\w+\s*=\s*require\s*\(\s*['"](?P<path>[^'"]+)['"]\s*\)"""
            ),
        ]

    def _python_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"from\s+(?P<path>[\w.]+)\s+import"),
            re.compile(r"import\s+(?P<path>[\w.]+)"),
        ]

    def _generic_import_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"from\s+(?P<path>[\w.]+)\s+import"),
            re.compile(r"import\s+(?P<path>[\w.]+)"),
            re.compile(r'require\s*\(\s*["\'](?P<path>[^"\']+)["\']\s*\)'),
            re.compile(r"use\s+(?P<path>[\w:]+)"),
            re.compile(r'#include\s*["<](?P<path>[^">]+)[">]'),
        ]

    # ------------------------------------------------------------------
    # Per-language: function patterns
    # ------------------------------------------------------------------

    def _go_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"func\s+\(\s*\w+\s+\*?\w+\s*\)\s+(?P<name>\w+)\s*\("),
            re.compile(r"func\s+(?P<name>\w+)\s*\("),
        ]

    def _rust_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"pub\s+(?:async\s+)?fn\s+(?P<name>\w+)\s*[\(<]"),
            re.compile(r"(?:async\s+)?fn\s+(?P<name>\w+)\s*[\(<]"),
        ]

    def _java_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"(?:public|private|protected|static)\s+[\w<>\[\]]+\s+(?P<name>\w+)\s*\("),
        ]

    def _ruby_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"def\s+(?P<name>[\w.?!]+)"),
        ]

    def _js_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"function\s+(?P<name>\w+)\s*\("),
            re.compile(r"(?:const|let|var)\s+(?P<name>\w+)\s*=\s*\("),
            re.compile(r"(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s+)?\("),
            re.compile(
                r"(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[\w]+)\s*=>"
            ),
        ]

    def _python_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            re.compile(r"(?:async\s+)?def\s+(?P<name>\w+)\s*\("),
        ]

    def _generic_function_patterns(self) -> list[re.Pattern[str]]:
        return [
            # Go: func with receiver
            re.compile(r"func\s+\(\s*\w+\s+\*?\w+\s*\)\s+(?P<name>\w+)\s*\("),
            # Go: func without receiver
            re.compile(r"func\s+(?P<name>\w+)\s*\("),
            # JavaScript/TypeScript: function declarations
            re.compile(r"function\s+(?P<name>\w+)\s*\("),
            # JavaScript/TypeScript: arrow functions and const fn = (
            re.compile(
                r"(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[\w]+)\s*=>"
            ),
            re.compile(r"(?:const|let|var)\s+(?P<name>\w+)\s*=\s*(?:async\s+)?\("),
            # Rust: pub fn and fn
            re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>\w+)\s*[\(<]"),
            # Ruby / Python: def
            re.compile(r"def\s+(?P<name>[\w.?!]+)"),
            # Java: compound modifiers (public/private/protected/static in any combo)
            re.compile(
                r"(?:(?:public|private|protected|static)\s+)+[\w<>\[\]]+\s+(?P<name>\w+)\s*\("
            ),
        ]

    # ------------------------------------------------------------------
    # Go multi-line import block handling
    # ------------------------------------------------------------------

    def _extract_go_multiline_imports(self, source: str, seen: set[str]) -> list[str]:
        """Parse ``import ( ... )`` blocks in Go source files."""
        results: list[str] = []
        in_block = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped == "import (":
                in_block = True
                continue
            if in_block:
                if stripped == ")":
                    in_block = False
                    continue
                m = re.match(r'^\s*"(?P<path>[^"]+)"', stripped)
                if m:
                    path = m.group("path")
                    if path and path not in seen:
                        seen.add(path)
                        results.append(path)
        return results

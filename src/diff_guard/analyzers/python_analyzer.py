from __future__ import annotations

import ast
from pathlib import Path


class PythonASTAnalyzer:
    """AST-based analyzer for Python source files using only stdlib ``ast``."""

    # ------------------------------------------------------------------
    # Import extraction
    # ------------------------------------------------------------------

    def extract_imports(self, source: str, file_path: str) -> list[str]:
        """Return list of imported module paths.

        For ``import os.path`` returns ``["os.path"]``.
        For ``from auth.login import authenticate`` returns ``["auth.login"]``.
        For relative imports the leading dots are preserved:
        ``from . import sibling`` -> ``".sibling"``.
        """
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []

        visitor = _ImportVisitor()
        visitor.visit(tree)
        return visitor.imports

    # ------------------------------------------------------------------
    # Function extraction
    # ------------------------------------------------------------------

    def extract_functions(self, source: str) -> list[tuple[str, int, int]]:
        """Return list of ``(function_name, start_line, end_line)``.

        Includes top-level functions, async functions, and methods inside
        classes.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        visitor = _FunctionVisitor()
        visitor.visit(tree)
        return visitor.functions

    # ------------------------------------------------------------------
    # Class extraction
    # ------------------------------------------------------------------

    def extract_classes(self, source: str) -> list[tuple[str, int, int]]:
        """Return list of ``(class_name, start_line, end_line)``."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        visitor = _ClassVisitor()
        visitor.visit(tree)
        return visitor.classes

    # ------------------------------------------------------------------
    # Line-to-function mapping
    # ------------------------------------------------------------------

    def line_to_function(self, source: str, line_numbers: list[int]) -> list[str]:
        """Map *line_numbers* to their enclosing function or class names."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        visitor = _ScopeVisitor()
        visitor.visit(tree)

        result: list[str] = []
        for lineno in line_numbers:
            best: str | None = None
            best_span = 0
            for name, start, end in visitor.scopes:
                if start <= lineno <= end:
                    span = end - start
                    # Prefer the most specific (smallest) enclosing scope
                    if best is None or span < best_span:
                        best = name
                        best_span = span
            if best is not None:
                result.append(best)
        return result

    # ------------------------------------------------------------------
    # Call extraction
    # ------------------------------------------------------------------

    def extract_calls(self, source: str) -> list[str]:
        """Extract all function/method call names from the source.

        For ``a.b.c()`` returns ``"a.b.c"``.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        visitor = _CallVisitor()
        visitor.visit(tree)
        return visitor.calls

    # ------------------------------------------------------------------
    # Module-path resolution
    # ------------------------------------------------------------------

    def resolve_module_path(self, import_path: str, project_root: Path) -> str | None:
        """Resolve a dotted import like ``'auth.login'`` to a relative file path.

        Returns a forward-slash path string (relative to *project_root*) or
        ``None`` when no matching file is found.
        """
        parts = import_path.replace(".", "/")
        # Candidate file paths to try, in order of preference:
        #   src/auth/login.py, auth/login.py,
        #   src/auth/login/__init__.py, auth/login/__init__.py
        candidates = [
            project_root / "src" / f"{parts}.py",
            project_root / f"{parts}.py",
            project_root / "src" / parts / "__init__.py",
            project_root / parts / "__init__.py",
        ]
        for candidate in candidates:
            if candidate.is_file():
                rel = candidate.relative_to(project_root)
                return rel.as_posix()
        return None


# ======================================================================
# Internal AST visitors
# ======================================================================


class _ImportVisitor(ast.NodeVisitor):
    """Collect top-level import module paths."""

    def __init__(self) -> None:
        self.imports: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level and node.level > 0:
            # Relative import: prefix with dots
            prefix = "." * node.level
            module = node.module or ""
            for alias in node.names:
                name = (
                    f"{prefix}{module}.{alias.name}"
                    if module
                    else f"{prefix}{alias.name}"
                )
                self.imports.append(name)
        elif node.module:
            self.imports.append(node.module)


class _FunctionVisitor(ast.NodeVisitor):
    """Collect ``(name, start_line, end_line)`` for all functions / methods."""

    def __init__(self) -> None:
        self.functions: list[tuple[str, int, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.functions.append((node.name, node.lineno, end))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.functions.append((node.name, node.lineno, end))
        self.generic_visit(node)


class _ClassVisitor(ast.NodeVisitor):
    """Collect ``(name, start_line, end_line)`` for class definitions."""

    def __init__(self) -> None:
        self.classes: list[tuple[str, int, int]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.classes.append((node.name, node.lineno, end))
        self.generic_visit(node)


class _ScopeVisitor(ast.NodeVisitor):
    """Collect function and class scopes for line-to-scope mapping."""

    def __init__(self) -> None:
        self.scopes: list[tuple[str, int, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.scopes.append((node.name, node.lineno, end))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.scopes.append((node.name, node.lineno, end))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.scopes.append((node.name, node.lineno, end))
        self.generic_visit(node)


class _CallVisitor(ast.NodeVisitor):
    """Collect dotted call names (e.g. ``a.b.c()`` -> ``"a.b.c"``)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        name = _resolve_call_name(node.func)
        if name is not None:
            self.calls.append(name)
        self.generic_visit(node)


def _resolve_call_name(node: ast.expr) -> str | None:
    """Resolve an AST call target to a dotted name string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _resolve_call_name(node.value)
        if base is not None:
            return f"{base}.{node.attr}"
        return node.attr
    return None


# ======================================================================
# Public convenience helper
# ======================================================================


def map_lines_to_functions(source: str, changed_lines: list[int]) -> list[str]:
    """Given *source* code and a list of changed line numbers, return unique
    function names touched by those lines."""
    analyzer = PythonASTAnalyzer()
    names = analyzer.line_to_function(source, changed_lines)
    # Preserve order but deduplicate
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result

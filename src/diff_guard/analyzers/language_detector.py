from __future__ import annotations

import warnings
from pathlib import Path

from diff_guard.analyzers.generic_analyzer import GenericAnalyzer
from diff_guard.analyzers.python_analyzer import PythonASTAnalyzer

# Extension -> language mapping (single-source of truth for language detection)
_EXTENSION_LANGUAGE: dict[str, str] = {
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

# Languages considered "well-supported" (full AST analysis).
_SUPPORTED_LANGUAGES: set[str] = {"python"}


def detect_language(file_path: str) -> str:
    """Detect the programming language of *file_path* from its extension."""
    suffix = Path(file_path).suffix.lower()
    return _EXTENSION_LANGUAGE.get(suffix, "unknown")


def detect_languages(file_paths: list[str], repo_root: Path) -> list[str]:
    """Return a ranked list of languages present in *file_paths*.

    The ranking is by frequency (most common first), then alphabetically for
    ties.  ``"unknown"`` entries are excluded.
    """
    counts: dict[str, int] = {}
    for fp in file_paths:
        lang = detect_language(fp)
        if lang != "unknown":
            counts[lang] = counts.get(lang, 0) + 1

    # Sort by count descending, then name ascending for stable ordering
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [lang for lang, _ in ranked]


def get_analyzer(language: str) -> PythonASTAnalyzer | GenericAnalyzer:
    """Return the appropriate analyzer for *language*.

    * ``"python"`` -> :class:`PythonASTAnalyzer`
    * ``"javascript"`` / ``"typescript"`` -> :class:`GenericAnalyzer` with a
      ``warnings.warn`` about tree-sitter support planned for v0.2.
    * anything else -> :class:`GenericAnalyzer`
    """
    if language == "python":
        return PythonASTAnalyzer()

    if language in ("javascript", "typescript"):
        warnings.warn(
            f"diff-guard: {language} support is limited. "
            "Full AST analysis via tree-sitter is planned for v0.2. "
            "Falling back to GenericAnalyzer.",
            stacklevel=2,
        )
        return GenericAnalyzer()

    return GenericAnalyzer()

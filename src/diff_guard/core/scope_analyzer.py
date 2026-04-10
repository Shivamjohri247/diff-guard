from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from diff_guard.models import Change, DiffGuardConfig, IntendedScope
from diff_guard.utils import prompt_extractor

# Common English stop words to filter out when extracting keywords.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "not",
        "no",
        "all",
        "any",
        "some",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "into",
        "than",
        "too",
        "very",
        "just",
        "about",
        "up",
        "out",
        "also",
        "only",
        "so",
    }
)

# Directories to skip when walking the project tree for keyword-to-file mapping.
_SKIP_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".git", "node_modules", ".tox", ".eggs", "venv", ".venv", "site-packages"}
)

# File extensions we recognise as source code.
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".c", ".cpp", ".h", ".hpp"}
)


class ScopeResolver:
    """Resolves intended scope using a strict priority chain (Amendment 2)."""

    def __init__(self, repo_root: Path, config: DiffGuardConfig | None = None) -> None:
        self.repo_root = repo_root
        self.config = config or DiffGuardConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        cli_scope: str | None = None,
        changes: list[Change] | None = None,
    ) -> IntendedScope:
        """Main entry: try each source in priority order, return first match."""
        # Priority 1 (confidence=1.0): Explicit prompt file
        scope = self._from_prompt_file()
        if scope is not None:
            return scope

        # Priority 2 (confidence=0.8): CLI argument
        if cli_scope is not None and cli_scope.strip():
            scope = self._from_cli_arg(cli_scope)
            if scope is not None:
                return scope

        # Priority 3 (confidence=0.6): Commit message
        scope = self._from_commit_message()
        if scope is not None:
            return scope

        # Priority 4 (confidence=0.3): Inference from diff structure
        return self._infer_from_diff(changes or [])

    # ------------------------------------------------------------------
    # Priority sources
    # ------------------------------------------------------------------

    def _from_prompt_file(self) -> IntendedScope | None:
        """Priority 1: Read .diff-guard-prompt file."""
        path = prompt_extractor.find_prompt_file(self.repo_root, self.config.scope)
        if path is None:
            return None
        content = prompt_extractor.read_prompt_file(path)
        if not content.strip():
            return None
        scope = self._parse_scope_text(content)
        scope.confidence = 1.0
        scope.source = "prompt_file"
        return self._enrich_with_project_areas(scope)

    def _from_cli_arg(self, scope_text: str) -> IntendedScope | None:
        """Priority 2: Parse CLI --scope argument."""
        scope = self._parse_scope_text(scope_text)
        scope.confidence = 0.8
        scope.source = "cli"
        return self._enrich_with_project_areas(scope)

    def _from_commit_message(self) -> IntendedScope | None:
        """Priority 3: Parse commit message."""
        # Import lazily to avoid circular dependency issues and to allow
        # testing without a real git repo.
        from diff_guard.utils.git import get_commit_message

        msg = get_commit_message(self.repo_root)
        if not msg.strip():
            return None
        scope = self._parse_scope_text(msg)
        scope.confidence = 0.6
        scope.source = "commit_message"
        return self._enrich_with_project_areas(scope)

    def _infer_from_diff(self, changes: list[Change]) -> IntendedScope:
        """Priority 4: Infer from diff structure. Group files by directory."""
        if not changes:
            return IntendedScope(
                description="No changes to analyse",
                target_files=set(),
                target_functions=set(),
                target_concepts=set(),
                confidence=0.3,
                source="inferred",
            )

        # Collect directories
        dir_counts: Counter[str] = Counter()
        all_files: set[str] = set()
        all_functions: set[str] = set()

        for change in changes:
            all_files.add(change.file_path)
            parent = str(Path(change.file_path).parent)
            dir_counts[parent] += 1
            for func in change.functions_modified:
                all_functions.add(func)

        # Most-changed directory is the root of intent
        primary_dir = dir_counts.most_common(1)[0][0] if dir_counts else ""

        # Extract module names from paths
        concepts: set[str] = set()
        for change in changes:
            parts = Path(change.file_path).parts
            for part in parts:
                stem = Path(part).stem
                if stem and stem not in _STOP_WORDS:
                    concepts.add(stem.lower())

        description = (
            f"Changes concentrated in {primary_dir}" if primary_dir else "Inferred from diff"
        )

        scope = IntendedScope(
            description=description,
            target_files=all_files,
            target_functions=all_functions,
            target_concepts=concepts,
            confidence=0.3,
            source="inferred",
        )
        return self._enrich_with_project_areas(scope)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_scope_text(self, text: str) -> IntendedScope:
        """Parse free-text scope into structured IntendedScope."""
        target_files: set[str] = set()
        target_functions: set[str] = set()

        # Extract file-like patterns: paths containing / or ending in a
        # recognised source extension.
        file_pattern = re.compile(
            r"(?:[\w./-]+/[\w./-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|rb|c|cpp|h|hpp)"
            r"|[\w.-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|rb|c|cpp|h|hpp))"
        )
        for match in file_pattern.finditer(text):
            target_files.add(match.group(0))

        # Extract function-like patterns: word followed by ()
        func_pattern = re.compile(r"\b([a-zA-Z_]\w*)\s*\(\)")
        for match in func_pattern.finditer(text):
            target_functions.add(match.group(1))

        # Extract keywords
        keywords = self._extract_keywords(text)
        target_concepts: set[str] = set(keywords)

        # Map keywords to file paths
        keyword_files = self._map_keywords_to_files(keywords)
        target_files.update(keyword_files)

        return IntendedScope(
            description=text.strip(),
            target_files=target_files,
            target_functions=target_functions,
            target_concepts=target_concepts,
            confidence=0.0,
            source="parsed",
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract technical nouns and verbs from scope text."""
        lowered = text.lower()
        tokens = re.split(r"[^a-z0-9_]+", lowered)
        return [t for t in tokens if t and t not in _STOP_WORDS and len(t) > 1]

    def _map_keywords_to_files(self, keywords: list[str]) -> set[str]:
        """Map keywords to likely file paths using path-matching."""
        if not keywords:
            return set()

        matched: set[str] = set()
        keyword_set = set(keywords)

        try:
            for dirpath, dirnames, filenames in os.walk(self.repo_root):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                rel_dir = str(Path(dirpath).relative_to(self.repo_root))

                # Match directory names
                for part in Path(rel_dir).parts:
                    if part.lower() in keyword_set:
                        for fname in filenames:
                            if Path(fname).suffix.lower() in _SOURCE_EXTENSIONS:
                                matched.add((Path(rel_dir) / fname).as_posix())

                # Match file stems
                for fname in filenames:
                    stem = Path(fname).stem.lower()
                    if stem in keyword_set:
                        matched.add((Path(rel_dir) / fname).as_posix())
        except OSError:
            pass

        return matched

    def _enrich_with_project_areas(self, scope: IntendedScope) -> IntendedScope:
        """Expand scope using config area definitions (Amendment 2)."""
        areas = self.config.scope.areas
        if not areas:
            return scope

        extra_files: set[str] = set()
        for area_name, area_def in areas.items():
            # Match if area name appears in concepts or description
            area_lower = area_name.lower()
            if area_lower in scope.target_concepts or area_lower in scope.description.lower():
                extra_files.update(area_def.get("files", []))
                extra_files.update(area_def.get("related", []))

        scope.target_files.update(extra_files)
        return scope

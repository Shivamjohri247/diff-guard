from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from diff_guard.models import Change, TestConfig, TestSuggestion

# FileGraph is built in Step 3; import it directly.  If the module does not
# exist yet (parallel development), fall back to None at *import* time so that
# the rest of TestMapper can still be tested.
try:
    from diff_guard.utils.file_graph import FileGraph
except ModuleNotFoundError:  # pragma: no cover
    FileGraph = None  # type: ignore[assignment, misc]


class TestMapper:
    """Maps changed files and functions to relevant test files."""

    def __init__(
        self,
        repo_root: Path,
        file_graph: FileGraph | None = None,
        config: TestConfig | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.file_graph = file_graph
        self.config = config or TestConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def map_changes_to_tests(self, changes: list[Change]) -> list[TestSuggestion]:
        """For each changed file, find relevant test files."""
        suggestions: list[TestSuggestion] = []
        seen: dict[str, float] = {}  # test_file -> best confidence so far

        for change in changes:
            if change.is_deleted:
                continue

            candidates = self._find_all_candidates(change)
            for sug in candidates:
                key = sug.test_file
                if key not in seen or seen[key] < sug.confidence:
                    seen[key] = sug.confidence
                    # Replace or add – keep highest confidence entry
                    suggestions = [s for s in suggestions if s.test_file != key]
                    suggestions.append(sug)

        return suggestions

    def find_test_files(self, source_file: str) -> list[str]:
        """Find test files for a given source file using name convention."""
        stem = Path(source_file).stem
        parent = Path(source_file).parent

        test_dirs = self._scan_test_directories()
        results: list[str] = []

        for tdir in test_dirs:
            # Walk all files in this test directory
            for tf in tdir.rglob("*"):
                if not tf.is_file():
                    continue
                if not self._matches_test_pattern(tf.name):
                    continue

                rel = tf.relative_to(self.repo_root)
                rel_str = str(rel)

                # Direct name match: test file stem contains source stem
                tf_stem = tf.stem
                # Strip common test prefixes/suffixes for matching
                match_stem = tf_stem
                for prefix in ("test_", "test-"):
                    if match_stem.startswith(prefix):
                        match_stem = match_stem[len(prefix):]
                        break
                for suffix in ("_test", "-test"):
                    if match_stem.endswith(suffix):
                        match_stem = match_stem[: -len(suffix)]
                        break

                if match_stem == stem:
                    results.append(rel_str)
                    continue

                # Directory-based match: test is under a subdirectory named
                # after the source file's parent (e.g. tests/auth/test_login.py
                # for auth/login.py)
                try:
                    test_rel_to_tdir = tf.relative_to(tdir)
                    parts = test_rel_to_tdir.parts
                    if len(parts) >= 2 and parts[0] == str(parent):
                        results.append(rel_str)
                        continue
                except ValueError:
                    pass

        return results

    def find_tests_by_import(self, source_file: str) -> list[str]:
        """Find test files that import the given source file (using file_graph)."""
        if self.file_graph is None:
            return []

        dependents = self.file_graph.dependents(source_file)
        results: list[str] = []
        for dep in dependents:
            if self._is_test_file(dep):
                results.append(dep)
        return results

    def find_tests_by_function(self, function_name: str) -> list[str]:
        """Find test files containing test_<function_name>."""
        test_dirs = self._scan_test_directories()
        pattern = re.compile(rf"\btest_{re.escape(function_name)}\b")
        results: list[str] = []

        for tdir in test_dirs:
            for tf in tdir.rglob("*"):
                if not tf.is_file():
                    continue
                if not self._is_test_file_by_name(tf.name):
                    continue
                try:
                    text = tf.read_text(errors="ignore")
                except OSError:
                    continue
                if pattern.search(text):
                    rel = tf.relative_to(self.repo_root)
                    results.append(str(rel))

        return results

    def suggest_test_command(self, suggestions: list[TestSuggestion]) -> str:
        """Generate a test command string from the suggestions."""
        if not suggestions:
            return ""
        files = sorted({sug.test_file for sug in suggestions})
        return self.config.command.format(files=" ".join(files))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_all_candidates(self, change: Change) -> list[TestSuggestion]:
        """Collect candidate test suggestions from all strategies."""
        source = change.file_path
        stem = Path(source).stem
        candidates: list[TestSuggestion] = []

        # 1. Convention-based (name match)
        name_matches = self.find_test_files(source)
        for tf in name_matches:
            # Determine confidence: direct stem match vs directory match
            tf_stem = Path(tf).stem
            match_stem = tf_stem
            for prefix in ("test_", "test-"):
                if match_stem.startswith(prefix):
                    match_stem = match_stem[len(prefix):]
                    break
            for suffix in ("_test", "-test"):
                if match_stem.endswith(suffix):
                    match_stem = match_stem[: -len(suffix)]
                    break

            if match_stem == stem:
                confidence = 0.9
                reason = "direct name match"
            else:
                confidence = 0.7
                reason = "directory match"

            candidates.append(
                TestSuggestion(
                    test_file=tf,
                    changed_file=source,
                    match_reason=reason,
                    confidence=confidence,
                )
            )

        # 2. Import-chain match
        import_matches = self.find_tests_by_import(source)
        for tf in import_matches:
            candidates.append(
                TestSuggestion(
                    test_file=tf,
                    changed_file=source,
                    match_reason="import chain match",
                    confidence=0.8,
                )
            )

        # 3. Function-level match
        for func_name in change.functions_modified:
            func_matches = self.find_tests_by_function(func_name)
            for tf in func_matches:
                candidates.append(
                    TestSuggestion(
                        test_file=tf,
                        changed_file=source,
                        match_reason=f"function match: {func_name}",
                        confidence=0.6,
                    )
                )

        return candidates

    def _scan_test_directories(self) -> list[Path]:
        """Discover test directories in the project."""
        dirs: list[Path] = []
        for pattern in self.config.directories:
            candidate = self.repo_root / pattern.rstrip("/")
            if candidate.is_dir():
                dirs.append(candidate)
        return dirs

    def _normalize_module_path(self, file_path: str) -> str:
        """Convert file path to module-like name for matching."""
        p = Path(file_path)
        parts = list(p.parts)
        # Remove extension from last part
        if parts:
            parts[-1] = Path(parts[-1]).stem
        return ".".join(parts)

    def _matches_test_pattern(self, filename: str) -> bool:
        """Check if a filename matches any configured test pattern."""
        for pat in self.config.patterns:
            if self._fnmatch(filename, pat):
                return True
        return False

    def _is_test_file(self, file_path: str) -> bool:
        """Check if a file path looks like a test file."""
        name = Path(file_path).name
        return self._is_test_file_by_name(name)

    def _is_test_file_by_name(self, filename: str) -> bool:
        """Check if a filename looks like a test file by pattern."""
        return self._matches_test_pattern(filename)

    @staticmethod
    def _fnmatch(name: str, pattern: str) -> bool:
        """Match *name* against a glob-style *pattern*."""
        return fnmatch.fnmatch(name, pattern)

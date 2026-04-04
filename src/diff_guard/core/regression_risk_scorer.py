from __future__ import annotations

from diff_guard.models import (
    Change,
    DiffGuardConfig,
    DownstreamImpact,
    IntendedScope,
    PhantomChange,
)
from diff_guard.utils.file_graph import FileGraph

# Factor weights – must sum to 1.0
_WEIGHT_SCOPE_OVERFLOW: float = 0.30
_WEIGHT_COMPLEXITY: float = 0.20
_WEIGHT_CENTRALITY: float = 0.20
_WEIGHT_TEST_COVERAGE: float = 0.15
_WEIGHT_DELETION_RISK: float = 0.15

# Normalisation ceiling for the complexity factor
_COMPLEXITY_LINE_CEILING: int = 500


class RegressionRiskScorer:
    """5-factor composite risk scoring."""

    def __init__(
        self,
        file_graph: FileGraph | None = None,
        config: DiffGuardConfig | None = None,
    ) -> None:
        self.file_graph = file_graph
        self.config = config or DiffGuardConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        changes: list[Change],
        scope: IntendedScope,
        phantom_changes: list[PhantomChange],
        downstream: list[DownstreamImpact],
    ) -> tuple[float, str]:
        """Return ``(risk_score: 0.0-1.0, risk_level: 'safe'|'review'|'danger')``."""
        test_files: set[str] = self._collect_test_files(changes)
        raw = self._weighted_score(changes, scope, phantom_changes, test_files)
        level = self.classify(raw, scope)
        return raw, level

    # ------------------------------------------------------------------
    # Individual factors
    # ------------------------------------------------------------------

    def factor_scope_overflow(
        self,
        changes: list[Change],
        scope: IntendedScope,
        phantom_changes: list[PhantomChange],
    ) -> float:
        """Weight 0.30: ratio of out-of-scope lines to total lines changed.

        If the scope confidence is below 0.3 we cannot reliably determine
        what is out-of-scope, so the factor defaults to 0.0.
        """
        if scope.confidence < 0.3:
            return 0.0

        phantom_lines = sum(p.added_lines + p.removed_lines for p in phantom_changes)
        total_lines = sum(c.added_lines + c.removed_lines for c in changes)

        if total_lines == 0:
            return 0.0

        return min(1.0, phantom_lines / total_lines)

    def factor_complexity(self, changes: list[Change]) -> float:
        """Weight 0.20: total lines changed, normalised to ``min(1.0, total/500)``."""
        total_lines = sum(c.added_lines + c.removed_lines for c in changes)
        return min(1.0, total_lines / _COMPLEXITY_LINE_CEILING)

    def factor_centrality(self, changes: list[Change]) -> float:
        """Weight 0.20: how many files depend on changed files, normalised.

        Returns 0.0 when no ``file_graph`` is available.
        """
        if self.file_graph is None or not changes:
            return 0.0

        centralities = [self.file_graph.centrality(c.file_path) for c in changes]
        max_c = max(centralities)
        if max_c == 0:
            return 0.0

        return sum(centralities) / (max_c * len(changes))

    def factor_test_coverage(
        self,
        changes: list[Change],
        test_files: set[str],
    ) -> float:
        """Weight 0.15: fraction of changed files *without* corresponding tests.

        Higher value means worse coverage.
        """
        if not changes:
            return 0.0

        files_with_tests = 0
        for change in changes:
            if self._has_test(change.file_path, test_files):
                files_with_tests += 1

        return 1.0 - (files_with_tests / len(changes))

    def factor_deletion_risk(self, changes: list[Change]) -> float:
        """Weight 0.15: ratio of deleted lines to total lines changed."""
        total_added = sum(c.added_lines for c in changes)
        total_removed = sum(c.removed_lines for c in changes)
        total_lines = total_added + total_removed

        if total_lines == 0:
            return 0.0

        return total_removed / total_lines

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, score: float, scope: IntendedScope) -> str:
        """Map *score* to a risk level with dynamic thresholds.

        * ``safe``: score < ``risk_safe`` (default 0.3)
        * ``review``: score in [``risk_safe``, ``risk_danger``)
        * ``danger``: score >= ``risk_danger`` (default 0.6)

        Amendment 6: if ``scope.confidence < 0.4`` the result is **never**
        ``"danger"`` — it is capped at ``"review"``.
        """
        if scope.confidence < 0.4 and score >= self.config.thresholds.risk_danger:
            return "review"

        if score < self.config.thresholds.risk_safe:
            return "safe"
        if score < self.config.thresholds.risk_danger:
            return "review"
        return "danger"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _weighted_score(
        self,
        changes: list[Change],
        scope: IntendedScope,
        phantom_changes: list[PhantomChange],
        test_files: set[str],
    ) -> float:
        """Compute the weighted sum of all five factors."""
        f_scope = self.factor_scope_overflow(changes, scope, phantom_changes)
        f_complexity = self.factor_complexity(changes)
        f_centrality = self.factor_centrality(changes)
        f_test = self.factor_test_coverage(changes, test_files)
        f_deletion = self.factor_deletion_risk(changes)

        return (
            _WEIGHT_SCOPE_OVERFLOW * f_scope
            + _WEIGHT_COMPLEXITY * f_complexity
            + _WEIGHT_CENTRALITY * f_centrality
            + _WEIGHT_TEST_COVERAGE * f_test
            + _WEIGHT_DELETION_RISK * f_deletion
        )

    @staticmethod
    def _collect_test_files(changes: list[Change]) -> set[str]:
        """Gather a heuristic set of test-file paths from *changes*.

        For the scorer we only need to know *whether* a test exists for a
        given source file, so we build a lightweight set from the change
        list itself plus simple naming heuristics.  The full ``TestMapper``
        is overkill here.
        """
        test_files: set[str] = set()
        for change in changes:
            name = change.file_path
            # If the change *is* a test file, record it
            if _looks_like_test(name):
                test_files.add(name)
        return test_files

    @staticmethod
    def _has_test(source_file: str, test_files: set[str]) -> bool:
        """Check whether *source_file* has a corresponding test file."""
        # Direct match (the file itself is a test)
        if source_file in test_files:
            return True

        # Convention-based heuristic: test_<stem>.py or <stem>_test.py
        stem = source_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        parent = source_file.rsplit("/", 1)[0] if "/" in source_file else ""
        candidates: list[str] = []
        if parent:
            candidates.append(f"{parent}/test_{stem}.py")
            candidates.append(f"tests/test_{stem}.py")
            candidates.append(f"test/{stem}_test.py")
        else:
            candidates.append(f"test_{stem}.py")
            candidates.append(f"tests/test_{stem}.py")
        return any(c in test_files for c in candidates)


def _looks_like_test(file_path: str) -> bool:
    """Return ``True`` if *file_path* looks like a test file."""
    name = file_path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")

from __future__ import annotations

from pathlib import Path

from diff_guard.core.regression_risk_scorer import (
    _WEIGHT_CENTRALITY,
    _WEIGHT_COMPLEXITY,
    _WEIGHT_DELETION_RISK,
    _WEIGHT_SCOPE_OVERFLOW,
    _WEIGHT_TEST_COVERAGE,
    RegressionRiskScorer,
)
from diff_guard.models import (
    Change,
    ChangeType,
    DiffGuardConfig,
    DownstreamImpact,
    Hunk,
    IntendedScope,
    PhantomChange,
    Thresholds,
)
from diff_guard.utils.file_graph import FileGraph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _change(
    file_path: str = "src/app.py",
    added: int = 10,
    removed: int = 5,
    change_type: ChangeType = ChangeType.MODIFIED,
) -> Change:
    return Change(
        file_path=file_path,
        change_type=change_type,
        hunks=[Hunk(0, 0, 0, 0, "")],
        added_lines=added,
        removed_lines=removed,
    )


def _scope(
    target_files: set[str] | None = None,
    confidence: float = 0.9,
) -> IntendedScope:
    return IntendedScope(
        description="test scope",
        target_files=target_files or {"src/app.py"},
        confidence=confidence,
    )


def _phantom(
    file_path: str = "src/other.py",
    added: int = 50,
    removed: int = 20,
) -> PhantomChange:
    return PhantomChange(
        file_path=file_path,
        reason="unrelated",
        relevance_score=0.8,
        change_summary="large unrelated change",
        severity="warning",
        confidence=0.9,
        added_lines=added,
        removed_lines=removed,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSafeScore:
    """Clean change, in scope, has tests -> score < 0.3."""

    def test_safe_score(self) -> None:
        changes = [_change(added=20, removed=5)]
        test_changes = [_change(file_path="tests/test_app.py", added=5, removed=0)]
        all_changes = changes + test_changes

        scope = _scope(target_files={"src/app.py"}, confidence=0.9)
        phantom_changes: list[PhantomChange] = []
        downstream: list[DownstreamImpact] = []

        scorer = RegressionRiskScorer(file_graph=None)
        raw, level = scorer.score(all_changes, scope, phantom_changes, downstream)

        assert raw < 0.3
        assert level == "safe"


class TestDangerScore:
    """Phantom changes + high centrality + no tests -> score > 0.6."""

    def test_danger_score(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        # Change a high-centrality file with no tests
        changes = [_change(file_path="auth/session.py", added=30, removed=10)]
        scope = _scope(target_files={"auth/login.py"}, confidence=0.9)
        phantom_changes = [_phantom(added=80, removed=40)]
        downstream: list[DownstreamImpact] = []

        scorer = RegressionRiskScorer(file_graph=graph)
        raw, level = scorer.score(changes, scope, phantom_changes, downstream)

        assert raw > 0.6
        assert level == "danger"


class TestScopeOverflowFactor:
    """Mostly out-of-scope changes -> high scope overflow."""

    def test_scope_overflow_high(self) -> None:
        changes = [_change(added=100, removed=50)]
        phantom_changes = [_phantom(added=120, removed=30)]
        scope = _scope(confidence=0.9)

        scorer = RegressionRiskScorer()
        result = scorer.factor_scope_overflow(changes, scope, phantom_changes)

        # phantom_lines = 150, total_lines = 200 -> 0.75
        assert result >= 0.7

    def test_scope_overflow_low_confidence(self) -> None:
        changes = [_change(added=100, removed=50)]
        phantom_changes = [_phantom(added=120, removed=30)]
        scope = _scope(confidence=0.2)

        scorer = RegressionRiskScorer()
        result = scorer.factor_scope_overflow(changes, scope, phantom_changes)

        assert result == 0.0

    def test_scope_overflow_no_changes(self) -> None:
        scorer = RegressionRiskScorer()
        result = scorer.factor_scope_overflow([], _scope(), [])
        assert result == 0.0


class TestComplexityFactor:
    """Large diff -> high complexity."""

    def test_small_diff(self) -> None:
        changes = [_change(added=10, removed=5)]
        scorer = RegressionRiskScorer()
        assert scorer.factor_complexity(changes) == 15 / 500

    def test_large_diff(self) -> None:
        changes = [_change(added=400, removed=200)]
        scorer = RegressionRiskScorer()
        assert scorer.factor_complexity(changes) == 1.0

    def test_exact_ceiling(self) -> None:
        changes = [_change(added=300, removed=200)]
        scorer = RegressionRiskScorer()
        assert scorer.factor_complexity(changes) == 1.0


class TestCentralityFactor:
    """Change to highly-central file -> high centrality."""

    def test_with_file_graph(self, simple_python_project: Path) -> None:
        graph = FileGraph(simple_python_project)
        graph.build()

        changes = [_change(file_path="auth/session.py")]
        scorer = RegressionRiskScorer(file_graph=graph)
        result = scorer.factor_centrality(changes)

        assert result == 1.0  # single file normalised against itself

    def test_without_file_graph(self) -> None:
        scorer = RegressionRiskScorer(file_graph=None)
        result = scorer.factor_centrality([_change()])
        assert result == 0.0

    def test_no_changes(self) -> None:
        scorer = RegressionRiskScorer()
        assert scorer.factor_centrality([]) == 0.0


class TestDeletionRiskFactor:
    """Mostly deletions -> high deletion risk."""

    def test_mostly_deletions(self) -> None:
        changes = [_change(added=5, removed=45)]
        scorer = RegressionRiskScorer()
        result = scorer.factor_deletion_risk(changes)
        assert result == 45 / 50
        assert result > 0.8

    def test_only_additions(self) -> None:
        changes = [_change(added=50, removed=0)]
        scorer = RegressionRiskScorer()
        result = scorer.factor_deletion_risk(changes)
        assert result == 0.0

    def test_balanced(self) -> None:
        changes = [_change(added=25, removed=25)]
        scorer = RegressionRiskScorer()
        assert scorer.factor_deletion_risk(changes) == 0.5

    def test_no_changes(self) -> None:
        scorer = RegressionRiskScorer()
        assert scorer.factor_deletion_risk([]) == 0.0


class TestConfidenceGating:
    """Low scope confidence prevents 'danger' classification."""

    def test_low_confidence_caps_at_review(self) -> None:
        scorer = RegressionRiskScorer()
        # score=0.8 with confidence < 0.4 should return "review" not "danger"
        result = scorer.classify(0.8, _scope(confidence=0.3))
        assert result == "review"

    def test_high_confidence_allows_danger(self) -> None:
        scorer = RegressionRiskScorer()
        result = scorer.classify(0.8, _scope(confidence=0.9))
        assert result == "danger"

    def test_safe_unaffected_by_confidence(self) -> None:
        scorer = RegressionRiskScorer()
        result = scorer.classify(0.1, _scope(confidence=0.1))
        assert result == "safe"

    def test_custom_thresholds(self) -> None:
        config = DiffGuardConfig(
            thresholds=Thresholds(risk_safe=0.2, risk_danger=0.5),
        )
        scorer = RegressionRiskScorer(config=config)

        assert scorer.classify(0.15, _scope(confidence=0.9)) == "safe"
        assert scorer.classify(0.35, _scope(confidence=0.9)) == "review"
        assert scorer.classify(0.6, _scope(confidence=0.9)) == "danger"


class TestWeightedSum:
    """Verify final score is the weighted sum of individual factors."""

    def test_weighted_sum(self) -> None:
        changes = [_change(added=50, removed=30)]
        phantom_changes = [_phantom(added=20, removed=10)]
        scope = _scope(confidence=0.9)
        test_files: set[str] = set()

        scorer = RegressionRiskScorer(file_graph=None)

        # Compute each factor manually
        f_scope = scorer.factor_scope_overflow(changes, scope, phantom_changes)
        f_complexity = scorer.factor_complexity(changes)
        f_centrality = scorer.factor_centrality(changes)
        f_test = scorer.factor_test_coverage(changes, test_files)
        f_deletion = scorer.factor_deletion_risk(changes)

        expected = (
            _WEIGHT_SCOPE_OVERFLOW * f_scope
            + _WEIGHT_COMPLEXITY * f_complexity
            + _WEIGHT_CENTRALITY * f_centrality
            + _WEIGHT_TEST_COVERAGE * f_test
            + _WEIGHT_DELETION_RISK * f_deletion
        )

        # Verify weights sum to 1.0
        total_weight = (
            _WEIGHT_SCOPE_OVERFLOW
            + _WEIGHT_COMPLEXITY
            + _WEIGHT_CENTRALITY
            + _WEIGHT_TEST_COVERAGE
            + _WEIGHT_DELETION_RISK
        )
        assert abs(total_weight - 1.0) < 1e-9

        # Verify score matches
        downstream: list[DownstreamImpact] = []
        raw, _level = scorer.score(changes, scope, phantom_changes, downstream)
        assert abs(raw - expected) < 1e-9

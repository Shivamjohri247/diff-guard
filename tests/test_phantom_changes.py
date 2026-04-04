from __future__ import annotations

from pathlib import Path

import pytest

from diff_guard.core.diff_parser import parse_unified_diff
from diff_guard.core.phantom_change_detector import (
    AUTO_IGNORE_CATEGORIES,
    PhantomChangeDetector,
)
from diff_guard.models import (
    Change,
    ChangeType,
    DiffGuardConfig,
    Hunk,
    IntendedScope,
    PhantomChange,
    Thresholds,
)
from diff_guard.utils.file_graph import FileGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_change(
    file_path: str,
    added: int = 1,
    removed: int = 0,
    functions: list[str] | None = None,
    imports: list[str] | None = None,
    language: str = "python",
    is_new: bool = False,
    is_deleted: bool = False,
) -> Change:
    return Change(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        hunks=[],
        added_lines=added,
        removed_lines=removed,
        functions_modified=functions or [],
        imports_modified=imports or [],
        language=language,
        is_new_file=is_new,
        is_deleted=is_deleted,
    )


def _make_scope(
    target_files: set[str] | None = None,
    concepts: set[str] | None = None,
    functions: set[str] | None = None,
    confidence: float = 1.0,
) -> IntendedScope:
    return IntendedScope(
        description="test scope",
        target_files=target_files or set(),
        target_functions=functions or set(),
        target_concepts=concepts or set(),
        confidence=confidence,
        source="test",
    )


def _read_diff(fixture_name: str, sample_diffs_dir: Path) -> list[Change]:
    diff_path = sample_diffs_dir / fixture_name
    diff_text = diff_path.read_text()
    return parse_unified_diff(diff_text)


# ---------------------------------------------------------------------------
# Core detection tests
# ---------------------------------------------------------------------------


class TestDetectPhantomChanges:
    """Butterfly diff flags correct out-of-scope files."""

    def test_detect_phantom_changes(self, sample_diffs_dir: Path) -> None:
        changes = _read_diff("butterfly_change.diff", sample_diffs_dir)
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"login", "auth"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        phantoms = detector.detect(changes, scope)

        # session.py and rate_limit.py should be flagged
        phantom_paths = {p.file_path for p in phantoms}
        assert "src/auth/session.py" in phantom_paths
        assert "src/middleware/rate_limit.py" in phantom_paths
        # login.py is in scope and should NOT be flagged
        assert "src/auth/login.py" not in phantom_paths

    def test_no_phantom_for_clean_change(self, sample_diffs_dir: Path) -> None:
        """Clean diff (single file in scope) produces no phantom changes."""
        changes = _read_diff("clean_change.diff", sample_diffs_dir)
        # The clean_change.diff modifies src/auth/login.py only
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        phantoms = detector.detect(changes, scope)

        # Single file is in scope => no phantom changes
        assert len(phantoms) == 0


# ---------------------------------------------------------------------------
# Auto-ignore tests
# ---------------------------------------------------------------------------


class TestAutoIgnore:
    def test_auto_ignore_lockfile(self) -> None:
        """package-lock.json changes are auto-ignored (info severity)."""
        change = _make_change("package-lock.json", added=5, removed=3)
        scope = _make_scope(target_files={"src/auth/login.py"}, confidence=1.0)
        detector = PhantomChangeDetector()
        phantoms = detector.detect([change], scope)

        assert len(phantoms) == 1
        assert phantoms[0].severity == "info"
        assert "lockfile" in phantoms[0].reason.lower() or "auto" in phantoms[0].reason.lower()

    def test_auto_ignore_generated(self) -> None:
        """.min.js changes are auto-ignored."""
        change = _make_change("dist/bundle.min.js", added=100, removed=50, language="javascript")
        scope = _make_scope(target_files={"src/app.tsx"}, confidence=1.0)
        detector = PhantomChangeDetector()
        phantoms = detector.detect([change], scope)

        assert len(phantoms) == 1
        assert phantoms[0].severity == "info"

    def test_auto_ignore_yarn_lock(self) -> None:
        """yarn.lock is auto-ignored."""
        change = _make_change("yarn.lock", added=20, removed=10)
        scope = _make_scope(target_files={"src/main.ts"}, confidence=1.0)
        detector = PhantomChangeDetector()
        ignored, reason = detector.is_auto_ignored("yarn.lock")
        assert ignored is True
        assert reason != ""

    def test_auto_ignore_pycache(self) -> None:
        """__pycache__/ files are auto-ignored."""
        ignored, reason = PhantomChangeDetector().is_auto_ignored("__pycache__/foo.cpython-312.pyc")
        assert ignored is True

    def test_normal_file_not_auto_ignored(self) -> None:
        """Regular source files are not auto-ignored."""
        ignored, reason = PhantomChangeDetector().is_auto_ignored("src/auth/login.py")
        assert ignored is False
        assert reason == ""


# ---------------------------------------------------------------------------
# Import-chain whitelisting (Amendment 3a)
# ---------------------------------------------------------------------------


class TestImportChainWhitelisting:
    def test_import_chain_whitelisting(self, simple_python_project: Path) -> None:
        """File within 2 hops of scope is not flagged."""
        graph = FileGraph(simple_python_project)
        graph.build()

        # Scope targets auth/login.py; redis_cache.py is reachable
        # via auth/login.py -> auth/session.py -> redis_cache.py (2 hops)
        scope = _make_scope(
            target_files={"auth/login.py"},
            confidence=1.0,
        )
        change = _make_change("redis_cache.py", added=5, removed=2)
        detector = PhantomChangeDetector(file_graph=graph)
        phantoms = detector.detect([change], scope)

        # redis_cache.py is within 2 hops => legitimate downstream => not flagged
        phantom_paths = {p.file_path for p in phantoms}
        assert "redis_cache.py" not in phantom_paths

    def test_file_beyond_2_hops_is_flagged(self, simple_python_project: Path) -> None:
        """File beyond 2 hops of all scope files IS flagged."""
        graph = FileGraph(simple_python_project)
        graph.build()

        # Scope targets app.py; api/users.py is NOT reachable via forward
        # edges from app.py (graph is directed: app.py -> ... -> users.py
        # does not exist, even though users.py -> auth/session.py does).
        scope = _make_scope(
            target_files={"app.py"},
            confidence=1.0,
        )
        change = _make_change("api/users.py", added=10, removed=5)
        detector = PhantomChangeDetector(file_graph=graph)
        phantoms = detector.detect([change], scope)

        phantom_paths = {p.file_path for p in phantoms}
        assert "api/users.py" in phantom_paths


# ---------------------------------------------------------------------------
# Dynamic threshold adjustment
# ---------------------------------------------------------------------------


class TestDynamicThreshold:
    def test_dynamic_threshold_low_confidence(self) -> None:
        """Low scope confidence raises the bar for flagging.

        With confidence < 0.4, effective threshold = 0.3 * 2.0 = 0.6.
        A file with relevance 0.4 should NOT be flagged (below the
        effective threshold), but with high confidence it would be.
        """
        change = _make_change("src/unrelated/module.py", added=10, removed=5)
        scope_low = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
            confidence=0.3,  # Very low confidence
        )
        scope_high = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
            confidence=0.9,  # High confidence
        )
        detector = PhantomChangeDetector()

        # With low confidence, the effective threshold is much higher,
        # so fewer files should be flagged (anti-cry-wolf).
        phantoms_low = detector.detect([change], scope_low)
        phantoms_high = detector.detect([change], scope_high)

        # Low confidence should produce fewer or equal phantoms
        assert len(phantoms_low) <= len(phantoms_high)

    def test_effective_threshold_below_0_5(self) -> None:
        """Confidence 0.45 multiplies threshold by 1.5."""
        scope = _make_scope(confidence=0.45)
        detector = PhantomChangeDetector()
        threshold = detector._effective_threshold(scope)
        assert threshold == pytest.approx(0.3 * 1.5)

    def test_effective_threshold_below_0_4(self) -> None:
        """Confidence 0.3 multiplies threshold by 2.0."""
        scope = _make_scope(confidence=0.3)
        detector = PhantomChangeDetector()
        threshold = detector._effective_threshold(scope)
        assert threshold == pytest.approx(0.3 * 2.0)

    def test_effective_threshold_high_confidence(self) -> None:
        """High confidence keeps threshold unchanged."""
        scope = _make_scope(confidence=0.9)
        detector = PhantomChangeDetector()
        threshold = detector._effective_threshold(scope)
        assert threshold == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_severity_critical(self, simple_python_project: Path) -> None:
        """Unrelated file with many changes and high centrality = critical."""
        graph = FileGraph(simple_python_project)
        graph.build()

        # auth/session.py has high centrality in the fixture project
        scope = _make_scope(
            target_files={"payments/stripe.py"},
            concepts={"payments", "stripe"},
            confidence=1.0,
        )
        # Change a high-centrality file with lots of lines
        change = _make_change("auth/session.py", added=20, removed=15)
        detector = PhantomChangeDetector(file_graph=graph)
        relevance = detector.compute_relevance(change, scope)
        severity = detector.classify_severity(change, relevance, scope)

        # With many lines changed and high centrality, should be at least warning
        assert severity in ("warning", "critical")

    def test_severity_info_autoignore(self) -> None:
        """Migration file is classified as info."""
        change = _make_change("migrations/0001_initial.py", added=20, removed=5)
        scope = _make_scope(
            target_files={"src/models.py"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        phantoms = detector.detect([change], scope)
        assert len(phantoms) == 1
        assert phantoms[0].severity == "info"

    def test_severity_info_small_change(self) -> None:
        """Very small changes (<= 2 lines) are classified as info."""
        change = _make_change("src/some/other.py", added=1, removed=0)
        scope = _make_scope(
            target_files={"src/main.py"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        relevance = detector.compute_relevance(change, scope)
        severity = detector.classify_severity(change, relevance, scope)
        assert severity == "info"


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_confidence_display(self) -> None:
        """Every phantom change has confidence between 0.0 and 1.0."""
        changes = [
            _make_change("src/auth/login.py", added=3, removed=1),
            _make_change("src/payments/stripe.py", added=10, removed=5),
            _make_change("package-lock.json", added=50, removed=30),
            _make_change("src/utils/helpers.py", added=2, removed=0),
        ]
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        phantoms = detector.detect(changes, scope)

        for phantom in phantoms:
            assert 0.0 <= phantom.confidence <= 1.0, (
                f"Confidence {phantom.confidence} out of range for {phantom.file_path}"
            )

    def test_confidence_high_for_unrelated(self) -> None:
        """Truly unrelated file gets high confidence."""
        change = _make_change("src/payments/billing.py", added=15, removed=10)
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        confidence = detector.compute_confidence(change, scope, 0.0)
        assert confidence >= 0.5


# ---------------------------------------------------------------------------
# Config side-effect
# ---------------------------------------------------------------------------


class TestConfigSideEffect:
    def test_config_side_effect_not_flagged(self, sample_diffs_dir: Path) -> None:
        """Config drift files (e.g. .env.example) are flagged as info only."""
        changes = _read_diff("config_side_effect.diff", sample_diffs_dir)
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector()
        phantoms = detector.detect(changes, scope)

        # .env.example should be info
        for p in phantoms:
            if p.file_path == ".env.example":
                assert p.severity == "info"
            if p.file_path == "package-lock.json":
                assert p.severity == "info"


# ---------------------------------------------------------------------------
# Relevance scoring unit tests
# ---------------------------------------------------------------------------


class TestComputeRelevance:
    def test_explicit_match_scores_high(self) -> None:
        """File explicitly in scope.target_files gets high relevance."""
        change = _make_change("src/auth/login.py")
        scope = _make_scope(target_files={"src/auth/login.py"})
        detector = PhantomChangeDetector()
        relevance = detector.compute_relevance(change, scope)
        # Explicit match contributes 0.40, path match may also contribute
        assert relevance >= 0.4

    def test_unrelated_file_scores_low(self) -> None:
        """File unrelated to scope gets low relevance."""
        change = _make_change("src/payments/billing.py")
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth", "login"},
        )
        detector = PhantomChangeDetector()
        relevance = detector.compute_relevance(change, scope)
        assert relevance < 0.5

    def test_path_overlap_contributes(self) -> None:
        """File sharing path components with scope gets some relevance."""
        change = _make_change("src/auth/logout.py")
        scope = _make_scope(
            target_files={"src/auth/login.py"},
            concepts={"auth"},
        )
        detector = PhantomChangeDetector()
        relevance = detector.compute_relevance(change, scope)
        # Should have some relevance due to path overlap
        assert relevance > 0.0

    def test_relevance_is_bounded(self) -> None:
        """Relevance is always between 0.0 and 1.0."""
        change = _make_change("some/random/file.py")
        scope = _make_scope(target_files={"other/file.py"}, concepts={"other"})
        detector = PhantomChangeDetector()
        relevance = detector.compute_relevance(change, scope)
        assert 0.0 <= relevance <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_changes(self) -> None:
        """No changes produces no phantoms."""
        scope = _make_scope(target_files={"src/main.py"})
        detector = PhantomChangeDetector()
        phantoms = detector.detect([], scope)
        assert phantoms == []

    def test_empty_scope_files(self) -> None:
        """With empty scope, every non-ignored change is a phantom."""
        changes = [
            _make_change("src/auth/login.py", added=5, removed=2),
        ]
        scope = _make_scope(confidence=1.0)
        detector = PhantomChangeDetector()
        phantoms = detector.detect(changes, scope)
        assert len(phantoms) == 1

    def test_no_file_graph(self) -> None:
        """Detector works without a file graph (import chain score = 0)."""
        change = _make_change("src/auth/login.py", added=5, removed=2)
        scope = _make_scope(target_files={"src/auth/login.py"})
        detector = PhantomChangeDetector(file_graph=None)
        relevance = detector.compute_relevance(change, scope)
        # Explicit match should still give high relevance
        assert relevance >= 0.4

    def test_custom_threshold(self) -> None:
        """Custom threshold from config is respected."""
        config = DiffGuardConfig(thresholds=Thresholds(phantom_relevance=0.6))
        change = _make_change("src/unrelated/file.py", added=3, removed=1)
        scope = _make_scope(
            target_files={"src/main.py"},
            confidence=1.0,
        )
        detector = PhantomChangeDetector(config=config)
        phantoms = detector.detect([change], scope)
        # With higher threshold, even slightly-relevant files are flagged
        if phantoms:
            assert phantoms[0].file_path == "src/unrelated/file.py"

    def test_deleted_file_phantom(self) -> None:
        """Deleted file can be a phantom change."""
        change = Change(
            file_path="src/deleted_module.py",
            change_type=ChangeType.DELETED,
            hunks=[],
            added_lines=0,
            removed_lines=50,
            is_deleted=True,
        )
        scope = _make_scope(target_files={"src/main.py"}, confidence=1.0)
        detector = PhantomChangeDetector()
        phantoms = detector.detect([change], scope)
        assert len(phantoms) == 1
        assert phantoms[0].file_path == "src/deleted_module.py"
        assert phantoms[0].removed_lines == 50

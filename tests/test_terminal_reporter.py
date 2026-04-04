from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from diff_guard.models import (
    BlastRadiusReport,
    Change,
    ChangeType,
    DownstreamImpact,
    Hunk,
    IntendedScope,
    PhantomChange,
    TestSuggestion,
)
from diff_guard.reporters.terminal_reporter import TerminalReporter


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def _hunk() -> Hunk:
    return Hunk(old_start=1, old_count=1, new_start=1, new_count=1, content="")


def _change(
    file_path: str = "src/auth/login.py",
    added: int = 45,
    removed: int = 12,
    functions: list[str] | None = None,
) -> Change:
    return Change(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        hunks=[_hunk()],
        added_lines=added,
        removed_lines=removed,
        functions_modified=functions or ["validate_email()", "validate_password()"],
    )


def _scope(
    description: str = "fix login form validation",
    target_files: set[str] | None = None,
) -> IntendedScope:
    return IntendedScope(
        description=description,
        target_files=target_files or {"src/auth/login.py"},
        target_functions={"validate_email", "validate_password"},
        target_concepts={"login", "validation"},
        confidence=0.9,
        source="inferred",
    )


def _phantom(
    file_path: str = "src/auth/session.py",
    reason: str = "Not mentioned in scope, but 1 hop from login.py via imports",
    severity: str = "warning",
    confidence: float = 0.72,
    added: int = 18,
    removed: int = 9,
) -> PhantomChange:
    return PhantomChange(
        file_path=file_path,
        reason=reason,
        relevance_score=0.6,
        change_summary="modified session handling",
        severity=severity,
        confidence=confidence,
        added_lines=added,
        removed_lines=removed,
    )


def _downstream(
    file_path: str = "src/api/users.py",
    distance: int = 1,
    via_files: list[str] | None = None,
    risk: float = 0.4,
) -> DownstreamImpact:
    return DownstreamImpact(
        file_path=file_path,
        distance=distance,
        via_files=via_files or ["src/auth/session.py"],
        risk_contribution=risk,
    )


def _test_suggestion(
    test_file: str = "tests/test_login.py",
    changed_file: str = "src/auth/login.py",
    match_reason: str = "name match",
    confidence: float = 0.95,
) -> TestSuggestion:
    return TestSuggestion(
        test_file=test_file,
        changed_file=changed_file,
        match_reason=match_reason,
        confidence=confidence,
    )


def _report(
    risk_score: float = 0.54,
    risk_level: str = "review",
    changes: list[Change] | None = None,
    phantoms: list[PhantomChange] | None = None,
    impacts: list[DownstreamImpact] | None = None,
    suggestions: list[TestSuggestion] | None = None,
) -> BlastRadiusReport:
    return BlastRadiusReport(
        changed_files=changes or [_change()],
        intended_scope=_scope(),
        phantom_changes=phantoms or [],
        downstream_impacts=impacts or [],
        risk_score=risk_score,
        risk_level=risk_level,
        suggested_tests=suggestions or [],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reporter() -> TerminalReporter:
    return TerminalReporter(no_color=True)


@pytest.fixture
def color_reporter() -> TerminalReporter:
    return TerminalReporter(no_color=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenderHeader:
    def test_render_header(self, reporter: TerminalReporter) -> None:
        scope = _scope()
        result = reporter.render_header(scope, file_count=7, added=142, removed=38)
        # Box must contain the title
        assert "diff-guard blast radius" in result
        # Box must contain scope description
        assert "fix login form validation" in result
        # Must contain file count and line stats
        assert "7" in result
        assert "+142" in result
        assert "-38" in result
        # Must have box-drawing characters
        assert "\u256d" in result  # TOP_LEFT
        assert "\u2570" in result  # BOTTOM_LEFT


class TestRenderRiskGauge:
    def test_render_risk_gauge_safe(self, reporter: TerminalReporter) -> None:
        result = reporter.render_risk_gauge(0.15, "safe")
        assert "SAFE" in result
        assert "0.15" in result
        # Gauge should have filled blocks
        assert "\u2588" in result
        assert "\u2591" in result

    def test_render_risk_gauge_danger(self, reporter: TerminalReporter) -> None:
        result = reporter.render_risk_gauge(0.85, "danger")
        assert "DANGER" in result
        assert "0.85" in result
        # High score means mostly filled
        assert "\u2588" in result


class TestRenderInScope:
    def test_render_in_scope(self, reporter: TerminalReporter) -> None:
        changes = [
            _change(
                "src/auth/login.py",
                45,
                12,
                ["validate_email()", "validate_password()"],
            ),
            _change("src/auth/forms.py", 20, 5, ["LoginForm()"]),
        ]
        scope = _scope(
            target_files={"src/auth/login.py", "src/auth/forms.py"}
        )
        result = reporter.render_in_scope(changes, scope)
        assert "In scope" in result
        assert "2 files" in result
        assert "src/auth/login.py" in result
        assert "src/auth/forms.py" in result
        assert "validate_email()" in result


class TestRenderPhantomChanges:
    def test_render_phantom_with_confidence(self, reporter: TerminalReporter) -> None:
        phantoms = [_phantom(confidence=0.72)]
        result = reporter.render_phantom_changes(phantoms)
        assert "Phantom changes" in result
        assert "src/auth/session.py" in result
        assert "72%" in result
        assert "Not mentioned in scope" in result


class TestRenderBlastRadius:
    def test_render_blast_radius_tree(self, reporter: TerminalReporter) -> None:
        impacts = [
            _downstream("src/api/users.py", distance=1, via_files=["src/auth/session.py"]),
            _downstream("src/api/dashboard.py", distance=2, via_files=["src/auth/session.py", "src/api/users.py"]),
        ]
        result = reporter.render_blast_radius(impacts)
        assert "Downstream blast radius" in result
        assert "src/api/users.py" in result
        assert "src/api/dashboard.py" in result
        # Should contain tree characters
        assert "\u251c" in result or "\u2514" in result


class TestNoColor:
    def test_no_color_when_disabled(self) -> None:
        os.environ["NO_COLOR"] = "1"
        try:
            reporter = TerminalReporter(no_color=False)
            assert reporter.no_color is True
            # Verify no ANSI escape sequences in output
            report = _report(phantoms=[_phantom()])
            result = reporter.render_report(report)
            assert "\033[" not in result
        finally:
            del os.environ["NO_COLOR"]

    def test_explicit_no_color_flag(self, reporter: TerminalReporter) -> None:
        report = _report(phantoms=[_phantom()])
        result = reporter.render_report(report)
        assert "\033[" not in result


class TestReportWidth:
    def test_report_width(self, reporter: TerminalReporter) -> None:
        report = _report(
            changes=[_change("src/auth/login.py", 45, 12)],
            phantoms=[
                _phantom(
                    "src/utils/very_long_directory_name/helpers.py",
                    "Some reason",
                    confidence=0.5,
                )
            ],
            impacts=[
                _downstream("src/api/users.py", 1),
            ],
            suggestions=[
                _test_suggestion(),
            ],
        )
        result = reporter.render_report(report)
        for line in result.split("\n"):
            # Allow a small margin for box edges and tree characters
            assert len(line) <= 90, f"Line too long ({len(line)}): {line!r}"


class TestFullReport:
    def test_full_report_renders(self, reporter: TerminalReporter) -> None:
        report = _report(
            risk_score=0.54,
            risk_level="review",
            changes=[_change()],
            phantoms=[_phantom()],
            impacts=[_downstream()],
            suggestions=[_test_suggestion()],
        )
        result = reporter.render_report(report)
        assert "diff-guard blast radius" in result
        assert "REVIEW" in result
        assert "In scope" in result
        assert "Phantom changes" in result
        assert "Downstream blast radius" in result
        assert "Suggested tests" in result
        assert "Recommendation" in result

    def test_safe_report_no_phantoms(self, reporter: TerminalReporter) -> None:
        report = _report(
            risk_score=0.15,
            risk_level="safe",
        )
        result = reporter.render_report(report)
        assert "SAFE" in result
        assert "Phantom changes" not in result
        assert "safe" in result.lower() or "SAFE" in result

    def test_danger_report(self, reporter: TerminalReporter) -> None:
        report = _report(
            risk_score=0.85,
            risk_level="danger",
            phantoms=[_phantom(severity="critical", confidence=0.9)],
            impacts=[
                _downstream("src/api/users.py", 1),
                _downstream("src/api/dashboard.py", 2),
            ],
        )
        result = reporter.render_report(report)
        assert "DANGER" in result
        assert "High risk" in result

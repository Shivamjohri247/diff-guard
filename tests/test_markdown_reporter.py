from __future__ import annotations

from diff_guard.models import (
    BlastRadiusReport,
    Change,
    ChangeType,
    CommitMessageQuality,
    DownstreamImpact,
    IntendedScope,
    PhantomChange,
    TestSuggestion,
)
from diff_guard.reporters.markdown_reporter import MarkdownReporter


def _scope(
    description: str = "modify app logic",
    target_files: set[str] | None = None,
) -> IntendedScope:
    return IntendedScope(
        description=description,
        target_files=target_files or {"src/app.py"},
        target_functions=set(),
        target_concepts={"app"},
        confidence=0.8,
        source="cli",
    )


def _change(file_path: str = "src/app.py") -> Change:
    return Change(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        hunks=[],
        added_lines=10,
        removed_lines=3,
    )


def _phantom(file_path: str = "src/utils.py") -> PhantomChange:
    return PhantomChange(
        file_path=file_path,
        reason="Not in scope",
        relevance_score=0.5,
        change_summary="modified utility functions",
        severity="warning",
        confidence=0.7,
        added_lines=5,
        removed_lines=2,
    )


def _downstream(file_path: str = "src/api.py") -> DownstreamImpact:
    return DownstreamImpact(
        file_path=file_path,
        distance=1,
        via_files=["src/app.py"],
        risk_contribution=0.3,
    )


def _suggestion(
    test_file: str = "tests/test_app.py",
    changed_file: str = "src/app.py",
) -> TestSuggestion:
    return TestSuggestion(
        test_file=test_file,
        changed_file=changed_file,
        match_reason="direct name match",
        confidence=0.9,
    )


def _quality(
    message: str = "fix: update app logic to handle edge cases",
    score: float = 0.8,
) -> CommitMessageQuality:
    return CommitMessageQuality(
        message=message,
        score=score,
        issues=[],
        is_vague=False,
        suggested_improvement=None,
    )


def _report(
    risk_score: float = 0.15,
    risk_level: str = "safe",
    changes: list[Change] | None = None,
    phantoms: list[PhantomChange] | None = None,
    impacts: list[DownstreamImpact] | None = None,
    suggestions: list[TestSuggestion] | None = None,
    quality: CommitMessageQuality | None = None,
) -> BlastRadiusReport:
    return BlastRadiusReport(
        changed_files=changes or [_change()],
        intended_scope=_scope(),
        phantom_changes=phantoms or [],
        downstream_impacts=impacts or [],
        risk_score=risk_score,
        risk_level=risk_level,
        suggested_tests=suggestions or [],
        commit_message_quality=quality,
    )


reporter = MarkdownReporter()


class TestMarkdownHeader:
    def test_header_present(self) -> None:
        result = reporter.render_report(_report())
        assert "diff-guard Blast Radius Report" in result

    def test_scope_description(self) -> None:
        result = reporter.render_report(_report())
        assert "**Scope**: modify app logic" in result

    def test_confidence_displayed(self) -> None:
        result = reporter.render_report(_report())
        assert "confidence: 0.80" in result

    def test_risk_level_displayed(self) -> None:
        result = reporter.render_report(_report(risk_level="review", risk_score=0.5))
        assert "**Risk Level**: review" in result
        assert "score: 0.50" in result


class TestMarkdownCommitQuality:
    def test_quality_section_present(self) -> None:
        quality = _quality()
        result = reporter.render_report(_report(quality=quality))
        assert "Commit Message Quality" in result

    def test_quality_score_displayed(self) -> None:
        quality = _quality(score=0.75)
        result = reporter.render_report(_report(quality=quality))
        assert "75%" in result

    def test_quality_message_quoted(self) -> None:
        quality = _quality(message="fix: update login\n\nDetailed description")
        result = reporter.render_report(_report(quality=quality))
        assert "> `fix: update login`" in result

    def test_quality_issues_listed(self) -> None:
        quality = CommitMessageQuality(
            message="fix",
            score=0.3,
            issues=["Message is too short", "Contains vague words"],
            is_vague=True,
            suggested_improvement="fix: resolve auth edge case in login handler",
        )
        result = reporter.render_report(_report(quality=quality))
        assert "- Message is too short" in result
        assert "- Contains vague words" in result

    def test_quality_suggestion(self) -> None:
        quality = CommitMessageQuality(
            message="wip",
            score=0.1,
            issues=["Vague message"],
            is_vague=True,
            suggested_improvement="feat: add user authentication module",
        )
        result = reporter.render_report(_report(quality=quality))
        assert "**Suggestion**: `feat: add user authentication module`" in result

    def test_no_quality_section_when_none(self) -> None:
        result = reporter.render_report(_report(quality=None))
        assert "Commit Message Quality" not in result


class TestMarkdownInScope:
    def test_in_scope_files_listed(self) -> None:
        result = reporter.render_report(_report())
        assert "In Scope" in result
        assert "- `src/app.py`" in result

    def test_in_scope_empty(self) -> None:
        scope = IntendedScope(
            description="test",
            target_files=set(),
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )
        report = BlastRadiusReport(
            changed_files=[_change()],
            intended_scope=scope,
            phantom_changes=[],
            downstream_impacts=[],
            risk_score=0.1,
            risk_level="safe",
            suggested_tests=[],
        )
        result = reporter.render_report(report)
        assert "_No files in scope._" in result


class TestMarkdownChangedFiles:
    def test_changed_files_listed(self) -> None:
        result = reporter.render_report(_report())
        assert "Changed Files" in result
        assert "`src/app.py` (modified, +10/-3)" in result

    def test_multiple_changes(self) -> None:
        changes = [_change("src/app.py"), _change("src/utils.py")]
        result = reporter.render_report(_report(changes=changes))
        assert "Changed Files (2)" in result
        assert "`src/app.py`" in result
        assert "`src/utils.py`" in result


class TestMarkdownPhantomChanges:
    def test_phantom_changes_present(self) -> None:
        result = reporter.render_report(_report(phantoms=[_phantom()]))
        assert "Phantom Changes" in result
        assert "`src/utils.py` [warning]" in result
        assert "Not in scope" in result

    def test_no_phantom_changes(self) -> None:
        result = reporter.render_report(_report())
        assert "_No phantom changes detected._" in result


class TestMarkdownDownstreamImpact:
    def test_downstream_impact_present(self) -> None:
        result = reporter.render_report(_report(impacts=[_downstream()]))
        assert "Downstream Impact" in result
        assert "`src/api.py`" in result
        assert "distance: 1" in result
        assert "via: src/app.py" in result

    def test_no_downstream_impact(self) -> None:
        result = reporter.render_report(_report())
        assert "_No downstream impact detected._" in result


class TestMarkdownSuggestedTests:
    def test_suggestions_present(self) -> None:
        result = reporter.render_report(_report(suggestions=[_suggestion()]))
        assert "Suggested Tests" in result
        assert "`tests/test_app.py`" in result
        assert "`src/app.py`" in result
        assert "confidence: 0.9" in result

    def test_no_suggestions(self) -> None:
        result = reporter.render_report(_report())
        assert "_No test suggestions._" in result


class TestMarkdownRecommendation:
    def test_safe_recommendation(self) -> None:
        result = reporter.render_report(_report(risk_level="safe"))
        assert "Changes appear safe" in result

    def test_review_recommendation(self) -> None:
        result = reporter.render_report(_report(risk_level="review"))
        assert "Some concerns detected" in result

    def test_danger_recommendation(self) -> None:
        result = reporter.render_report(_report(risk_level="danger"))
        assert "High risk detected" in result

    def test_recommendation_header(self) -> None:
        result = reporter.render_report(_report())
        assert "Recommendation" in result

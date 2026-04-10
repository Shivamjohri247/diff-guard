"""Tests for SARIF v2.1.0 reporter."""

from __future__ import annotations

import json

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
from diff_guard.reporters.sarif_reporter import SARIFReporter


def _make_report(
    risk_level: str = "safe",
    risk_score: float = 0.1,
    phantoms: list[PhantomChange] | None = None,
    downstream: list[DownstreamImpact] | None = None,
    commit_quality: CommitMessageQuality | None = None,
) -> BlastRadiusReport:
    return BlastRadiusReport(
        changed_files=[
            Change(
                file_path="src/main.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            )
        ],
        intended_scope=IntendedScope(
            description="test",
            target_files={"src/main.py"},
            confidence=0.8,
        ),
        phantom_changes=phantoms or [],
        downstream_impacts=downstream or [],
        risk_score=risk_score,
        risk_level=risk_level,
        suggested_tests=[
            TestSuggestion(
                test_file="tests/test_main.py",
                changed_file="src/main.py",
                match_reason="name match",
                confidence=0.9,
            )
        ],
        commit_message_quality=commit_quality,
    )


class TestSARIFSchema:
    def test_valid_sarif_structure(self) -> None:
        report = _make_report()
        output = SARIFReporter().render_report(report)
        data = json.loads(output)

        assert data["version"] == "2.1.0"
        assert "$schema" in data
        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert run["tool"]["driver"]["name"] == "diff-guard"
        assert "rules" in run["tool"]["driver"]
        assert "results" in run

    def test_rules_defined(self) -> None:
        report = _make_report()
        output = SARIFReporter().render_report(report)
        data = json.loads(output)

        rules = data["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = [r["id"] for r in rules]
        assert "DG001" in rule_ids
        assert "DG002" in rule_ids
        assert "DG003" in rule_ids
        assert "DG004" in rule_ids


class TestPhantomMapping:
    def test_phantom_change_mapped(self) -> None:
        phantom = PhantomChange(
            file_path="src/unrelated.py",
            reason="Out of scope",
            relevance_score=0.8,
            change_summary="modified",
            severity="warning",
            confidence=0.9,
            added_lines=3,
            removed_lines=1,
        )
        report = _make_report(phantoms=[phantom])
        data = json.loads(SARIFReporter().render_report(report))

        phantom_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG001"]
        assert len(phantom_results) == 1
        assert phantom_results[0]["level"] == "warning"
        assert (
            phantom_results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            == "src/unrelated.py"
        )

    def test_critical_severity_maps_to_error(self) -> None:
        phantom = PhantomChange(
            file_path="src/critical.py",
            reason="Dangerous change",
            relevance_score=0.95,
            change_summary="modified",
            severity="critical",
            confidence=0.95,
        )
        report = _make_report(phantoms=[phantom])
        data = json.loads(SARIFReporter().render_report(report))

        phantom_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG001"]
        assert phantom_results[0]["level"] == "error"

    def test_info_severity_maps_to_note(self) -> None:
        phantom = PhantomChange(
            file_path="package-lock.json",
            reason="Auto-generated",
            relevance_score=0.1,
            change_summary="modified",
            severity="info",
            confidence=0.5,
        )
        report = _make_report(phantoms=[phantom])
        data = json.loads(SARIFReporter().render_report(report))

        phantom_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG001"]
        assert phantom_results[0]["level"] == "note"


class TestDownstreamMapping:
    def test_downstream_impact_mapped(self) -> None:
        impact = DownstreamImpact(
            file_path="src/consumer.py",
            distance=2,
            via_files=["src/main.py", "src/middle.py"],
            risk_contribution=0.4,
        )
        report = _make_report(downstream=[impact])
        data = json.loads(SARIFReporter().render_report(report))

        downstream_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG002"]
        assert len(downstream_results) == 1
        assert (
            downstream_results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            == "src/consumer.py"
        )


class TestRiskMapping:
    def test_danger_risk_mapped(self) -> None:
        report = _make_report(risk_level="danger", risk_score=0.8)
        data = json.loads(SARIFReporter().render_report(report))

        risk_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG003"]
        assert len(risk_results) == 1
        assert risk_results[0]["level"] == "error"

    def test_review_risk_mapped(self) -> None:
        report = _make_report(risk_level="review", risk_score=0.5)
        data = json.loads(SARIFReporter().render_report(report))

        risk_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG003"]
        assert len(risk_results) == 1
        assert risk_results[0]["level"] == "warning"

    def test_safe_risk_not_mapped(self) -> None:
        report = _make_report(risk_level="safe", risk_score=0.1)
        data = json.loads(SARIFReporter().render_report(report))

        risk_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG003"]
        assert len(risk_results) == 0


class TestCommitQualityMapping:
    def test_low_quality_commit_mapped(self) -> None:
        quality = CommitMessageQuality(
            message="fix",
            score=0.1,
            issues=["Vague commit message"],
            is_vague=True,
            suggested_improvement="feat(main): update main module",
        )
        report = _make_report(commit_quality=quality)
        data = json.loads(SARIFReporter().render_report(report))

        quality_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG004"]
        assert len(quality_results) == 1
        assert quality_results[0]["level"] == "warning"
        assert quality_results[0]["properties"]["isVague"] is True

    def test_high_quality_commit_not_mapped(self) -> None:
        quality = CommitMessageQuality(
            message="feat(auth): add OAuth2 login",
            score=0.9,
            issues=[],
            is_vague=False,
        )
        report = _make_report(commit_quality=quality)
        data = json.loads(SARIFReporter().render_report(report))

        quality_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG004"]
        assert len(quality_results) == 0


class TestEmptyReport:
    def test_no_results_when_clean(self) -> None:
        report = _make_report()
        data = json.loads(SARIFReporter().render_report(report))
        assert data["runs"][0]["results"] == []


class TestSARIFBoundary:
    def test_no_commit_quality_field(self) -> None:
        """Report with commit_message_quality=None should not have DG004 result."""
        report = _make_report(commit_quality=None)
        data = json.loads(SARIFReporter().render_report(report))
        quality_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG004"]
        assert len(quality_results) == 0

    def test_multiple_phantom_changes(self) -> None:
        """Multiple phantom changes each produce a separate result."""
        phantoms = [
            PhantomChange(
                file_path=f"src/file{i}.py",
                reason=f"Reason {i}",
                relevance_score=0.5,
                change_summary="modified",
                severity="warning",
                confidence=0.7,
            )
            for i in range(3)
        ]
        report = _make_report(phantoms=phantoms)
        data = json.loads(SARIFReporter().render_report(report))

        phantom_results = [r for r in data["runs"][0]["results"] if r["ruleId"] == "DG001"]
        assert len(phantom_results) == 3

    def test_sarif_output_is_valid_json(self) -> None:
        """Output is always valid JSON."""
        report = _make_report(
            risk_level="danger",
            risk_score=0.9,
            phantoms=[
                PhantomChange(
                    file_path="x.py",
                    reason="r",
                    relevance_score=0.5,
                    change_summary="m",
                    severity="critical",
                    confidence=0.8,
                )
            ],
            downstream=[
                DownstreamImpact(
                    file_path="y.py",
                    distance=2,
                    via_files=["x.py"],
                    risk_contribution=0.3,
                )
            ],
            commit_quality=CommitMessageQuality(
                message="fix",
                score=0.1,
                issues=["vague"],
                is_vague=True,
            ),
        )
        output = SARIFReporter().render_report(report)
        data = json.loads(output)  # Should not raise
        assert len(data["runs"][0]["results"]) >= 3

    def test_schema_uri(self) -> None:
        report = _make_report()
        data = json.loads(SARIFReporter().render_report(report))
        assert "sarif" in data["$schema"].lower()

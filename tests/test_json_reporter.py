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
from diff_guard.reporters.json_reporter import JSONReporter, _to_serializable


def _scope() -> IntendedScope:
    return IntendedScope(
        description="modify app logic",
        target_files={"src/app.py"},
        target_functions={"main"},
        target_concepts={"app"},
        confidence=0.8,
        source="cli",
    )


def _change() -> Change:
    return Change(
        file_path="src/app.py",
        change_type=ChangeType.MODIFIED,
        hunks=[],
        added_lines=10,
        removed_lines=3,
    )


def _report(
    risk_score: float = 0.15,
    risk_level: str = "safe",
    quality: CommitMessageQuality | None = None,
) -> BlastRadiusReport:
    return BlastRadiusReport(
        changed_files=[_change()],
        intended_scope=_scope(),
        phantom_changes=[],
        downstream_impacts=[],
        risk_score=risk_score,
        risk_level=risk_level,
        suggested_tests=[],
        commit_message_quality=quality,
    )


reporter = JSONReporter()


class TestToSerializable:
    def test_dataclass(self) -> None:
        change = _change()
        result = _to_serializable(change)
        assert isinstance(result, dict)
        assert result["file_path"] == "src/app.py"
        assert result["change_type"] == "modified"

    def test_set_converted_to_sorted_list(self) -> None:
        result = _to_serializable({"c", "a", "b"})
        assert result == ["a", "b", "c"]

    def test_list_recursed(self) -> None:
        result = _to_serializable([_change(), _change()])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["file_path"] == "src/app.py"

    def test_dict_recursed(self) -> None:
        result = _to_serializable({"key": {"nested": "value"}})
        assert result == {"key": {"nested": "value"}}

    def test_tuple_converted_to_list(self) -> None:
        result = _to_serializable((1, 2, 3))
        assert result == [1, 2, 3]

    def test_enum_converted_to_value(self) -> None:
        result = _to_serializable(ChangeType.MODIFIED)
        assert result == "modified"

    def test_primitive_passthrough(self) -> None:
        assert _to_serializable(42) == 42
        assert _to_serializable("hello") == "hello"
        assert _to_serializable(0.5) == 0.5
        assert _to_serializable(True) is True
        assert _to_serializable(None) is None

    def test_nested_dataclass(self) -> None:
        report = _report()
        result = _to_serializable(report)
        assert isinstance(result, dict)
        assert "changed_files" in result
        assert "intended_scope" in result
        assert isinstance(result["intended_scope"], dict)
        assert isinstance(result["intended_scope"]["target_files"], list)


class TestJSONReporterRenderReport:
    def test_produces_valid_json(self) -> None:
        result = reporter.render_report(_report())
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_top_level_fields(self) -> None:
        result = reporter.render_report(_report())
        data = json.loads(result)
        assert "changed_files" in data
        assert "intended_scope" in data
        assert "phantom_changes" in data
        assert "downstream_impacts" in data
        assert "risk_score" in data
        assert "risk_level" in data
        assert "suggested_tests" in data

    def test_changed_file_structure(self) -> None:
        result = reporter.render_report(_report())
        data = json.loads(result)
        assert len(data["changed_files"]) == 1
        assert data["changed_files"][0]["file_path"] == "src/app.py"
        assert data["changed_files"][0]["change_type"] == "modified"
        assert data["changed_files"][0]["added_lines"] == 10
        assert data["changed_files"][0]["removed_lines"] == 3

    def test_scope_structure(self) -> None:
        result = reporter.render_report(_report())
        data = json.loads(result)
        scope = data["intended_scope"]
        assert scope["description"] == "modify app logic"
        assert isinstance(scope["target_files"], list)
        assert "src/app.py" in scope["target_files"]
        assert isinstance(scope["target_concepts"], list)

    def test_risk_values(self) -> None:
        result = reporter.render_report(_report(risk_score=0.65, risk_level="review"))
        data = json.loads(result)
        assert data["risk_score"] == 0.65
        assert data["risk_level"] == "review"

    def test_commit_quality_included(self) -> None:
        quality = CommitMessageQuality(
            message="fix: update app logic",
            score=0.8,
            issues=[],
            is_vague=False,
            suggested_improvement=None,
        )
        result = reporter.render_report(_report(quality=quality))
        data = json.loads(result)
        assert data["commit_message_quality"]["message"] == "fix: update app logic"
        assert data["commit_message_quality"]["score"] == 0.8
        assert data["commit_message_quality"]["is_vague"] is False

    def test_commit_quality_none_when_absent(self) -> None:
        result = reporter.render_report(_report())
        data = json.loads(result)
        assert data["commit_message_quality"] is None

    def test_report_with_all_sections(self) -> None:
        report = BlastRadiusReport(
            changed_files=[_change()],
            intended_scope=_scope(),
            phantom_changes=[
                PhantomChange(
                    file_path="src/utils.py",
                    reason="out of scope",
                    relevance_score=0.5,
                    change_summary="modified helper",
                    severity="warning",
                    confidence=0.7,
                    added_lines=5,
                    removed_lines=2,
                )
            ],
            downstream_impacts=[
                DownstreamImpact(
                    file_path="src/api.py",
                    distance=1,
                    via_files=["src/app.py"],
                    risk_contribution=0.3,
                )
            ],
            risk_score=0.5,
            risk_level="review",
            suggested_tests=[
                TestSuggestion(
                    test_file="tests/test_app.py",
                    changed_file="src/app.py",
                    match_reason="name match",
                    confidence=0.9,
                )
            ],
            commit_message_quality=CommitMessageQuality(
                message="update app",
                score=0.4,
                issues=["No conventional commit prefix"],
                is_vague=False,
                suggested_improvement="feat: update app logic",
            ),
        )
        result = reporter.render_report(report)
        data = json.loads(result)
        assert len(data["phantom_changes"]) == 1
        assert data["phantom_changes"][0]["file_path"] == "src/utils.py"
        assert len(data["downstream_impacts"]) == 1
        assert data["downstream_impacts"][0]["distance"] == 1
        assert len(data["suggested_tests"]) == 1
        assert data["commit_message_quality"]["score"] == 0.4

    def test_sets_are_sorted_lists(self) -> None:
        result = reporter.render_report(_report())
        data = json.loads(result)
        # target_files is a set in the model, should be a sorted list in JSON
        assert isinstance(data["intended_scope"]["target_files"], list)
        assert data["intended_scope"]["target_files"] == sorted(
            data["intended_scope"]["target_files"]
        )

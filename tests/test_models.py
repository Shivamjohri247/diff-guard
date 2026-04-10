from __future__ import annotations

from diff_guard.models import (
    BlastRadiusReport,
    Change,
    ChangeType,
    CommitMessageQuality,
    DiffGuardConfig,
    DownstreamImpact,
    HookConfig,
    Hunk,
    IntendedScope,
    PhantomChange,
    ScopeConfig,
    TestConfig,
)


class TestChangeType:
    def test_values(self) -> None:
        assert ChangeType.MODIFIED.value == "modified"
        assert ChangeType.ADDED.value == "added"
        assert ChangeType.DELETED.value == "deleted"
        assert ChangeType.RENAMED.value == "renamed"


class TestHunk:
    def test_creation(self) -> None:
        hunk = Hunk(old_start=1, old_count=5, new_start=1, new_count=7, content="line")
        assert hunk.old_start == 1
        assert hunk.old_count == 5
        assert hunk.new_count == 7


class TestChange:
    def test_defaults(self) -> None:
        change = Change(
            file_path="app.py",
            change_type=ChangeType.MODIFIED,
            hunks=[],
            added_lines=5,
            removed_lines=2,
        )
        assert change.functions_modified == []
        assert change.imports_modified == []
        assert change.is_new_file is False
        assert change.is_deleted is False

    def test_with_functions(self) -> None:
        change = Change(
            file_path="app.py",
            change_type=ChangeType.MODIFIED,
            hunks=[],
            added_lines=5,
            removed_lines=2,
            functions_modified=["main", "helper"],
        )
        assert len(change.functions_modified) == 2


class TestIntendedScope:
    def test_defaults(self) -> None:
        scope = IntendedScope(
            description="test",
            target_files={"app.py"},
            confidence=0.8,
            source="cli",
        )
        assert scope.target_functions == set()
        assert scope.target_concepts == set()

    def test_with_all_fields(self) -> None:
        scope = IntendedScope(
            description="auth module",
            target_files={"auth.py"},
            target_functions={"login"},
            target_concepts={"auth"},
            confidence=0.9,
            source="inferred",
        )
        assert "login" in scope.target_functions
        assert "auth" in scope.target_concepts


class TestCommitMessageQuality:
    def test_defaults(self) -> None:
        quality = CommitMessageQuality(
            message="fix bug",
            score=0.5,
            issues=[],
            is_vague=False,
        )
        assert quality.suggested_improvement is None
        assert quality.issues == []


class TestPhantomChange:
    def test_creation(self) -> None:
        phantom = PhantomChange(
            file_path="utils.py",
            reason="out of scope",
            relevance_score=0.6,
            change_summary="modified helper",
            severity="warning",
            confidence=0.7,
            added_lines=5,
            removed_lines=2,
        )
        assert phantom.severity == "warning"


class TestDownstreamImpact:
    def test_creation(self) -> None:
        impact = DownstreamImpact(
            file_path="api.py",
            distance=2,
            via_files=["app.py", "api.py"],
            risk_contribution=0.4,
        )
        assert impact.distance == 2
        assert len(impact.via_files) == 2


class TestBlastRadiusReport:
    def test_minimal_report(self) -> None:
        report = BlastRadiusReport(
            changed_files=[],
            intended_scope=IntendedScope(
                description="test",
                target_files=set(),
                confidence=0.5,
                source="cli",
            ),
            phantom_changes=[],
            downstream_impacts=[],
            risk_score=0.0,
            risk_level="safe",
            suggested_tests=[],
        )
        assert report.commit_message_quality is None
        assert report.changed_files == []

    def test_with_commit_quality(self) -> None:
        quality = CommitMessageQuality(
            message="feat: add login",
            score=0.9,
            issues=[],
            is_vague=False,
        )
        report = BlastRadiusReport(
            changed_files=[],
            intended_scope=IntendedScope(
                description="test",
                target_files=set(),
                confidence=0.5,
                source="cli",
            ),
            phantom_changes=[],
            downstream_impacts=[],
            risk_score=0.0,
            risk_level="safe",
            suggested_tests=[],
            commit_message_quality=quality,
        )
        assert report.commit_message_quality.score == 0.9


class TestConfigDefaults:
    def test_diff_guard_config_defaults(self) -> None:
        config = DiffGuardConfig()
        assert config.ignore == []
        assert isinstance(config.tests, TestConfig)
        assert isinstance(config.scope, ScopeConfig)
        assert isinstance(config.hook, HookConfig)

    def test_test_config_defaults(self) -> None:
        config = TestConfig()
        assert "test_*.py" in config.patterns
        assert "*_test.py" in config.patterns
        assert config.command == "pytest {files} -v"

    def test_scope_config_defaults(self) -> None:
        config = ScopeConfig()
        assert ".diff-guard-prompt" in config.prompt_files
        assert config.areas == {}

    def test_hook_config_defaults(self) -> None:
        config = HookConfig()
        assert config.fail_on == "danger"
        assert config.mode == "full"

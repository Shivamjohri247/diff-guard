from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from diff_guard.cli import cmd_check, cmd_test, create_parser


class TestNoArgsShowsHelp:
    """Running diff-guard with no args exits 0."""

    def test_test_command_no_args_shows_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "from diff_guard.cli import main; main()"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "diff-guard" in result.stdout


class TestCmdTestNoChanges:
    """When there are no staged changes, cmd_test prints an appropriate message."""

    def test_test_command_no_changes(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["test"])

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value=""),
        ):
            ret = cmd_test(args)

        assert ret == 0


class TestCmdTestWithChanges:
    """cmd_test with various flags and mock changes."""

    def _make_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["test"] + extra)

    def test_human_readable_output(self) -> None:
        from diff_guard.models import Change, ChangeType

        args = self._make_args([])
        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]

        mock_mapper = MagicMock()
        mock_mapper.map_changes_to_tests.return_value = []
        mock_mapper.suggest_test_command.return_value = ""

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_test(args)

        assert ret == 0
        mock_mapper.map_changes_to_tests.assert_called_once_with(changes)

    def test_command_only_flag(self) -> None:
        from diff_guard.models import TestSuggestion

        args = self._make_args(["--command-only"])
        suggestions = [
            TestSuggestion(
                test_file="tests/test_app.py",
                changed_file="src/app.py",
                match_reason="direct name match",
                confidence=0.9,
            ),
        ]

        mock_mapper = MagicMock()
        mock_mapper.map_changes_to_tests.return_value = suggestions
        mock_mapper.suggest_test_command.return_value = "pytest tests/test_app.py -v"

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch(
                "diff_guard.core.diff_parser.parse_unified_diff",
                return_value=[MagicMock(file_path="src/app.py", is_deleted=False)],
            ),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_test(args)

        assert ret == 0
        mock_mapper.suggest_test_command.assert_called_once_with(suggestions)

    def test_json_flag(self) -> None:
        from diff_guard.models import Change, ChangeType, TestSuggestion

        args = self._make_args(["--json"])
        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]
        suggestions = [
            TestSuggestion(
                test_file="tests/test_app.py",
                changed_file="src/app.py",
                match_reason="direct name match",
                confidence=0.9,
            ),
        ]

        mock_mapper = MagicMock()
        mock_mapper.map_changes_to_tests.return_value = suggestions
        mock_mapper.suggest_test_command.return_value = "pytest tests/test_app.py -v"

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_mapper),
            patch("sys.stdout") as mock_stdout,
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_test(args)
            # Verify JSON was printed
            "".join(call.args[0] for call in mock_stdout.write.call_args_list)

        assert ret == 0

    def test_last_commit_flag(self) -> None:
        args = self._make_args(["--last-commit"])

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_last_commit_diff", return_value=""),
        ):
            ret = cmd_test(args)

        assert ret == 0

    def test_diff_ref_flag(self) -> None:
        args = self._make_args(["--diff", "HEAD~3"])

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_diff_from_ref", return_value=""),
        ):
            ret = cmd_test(args)

        assert ret == 0


# ---------------------------------------------------------------------------
# cmd_check tests
# ---------------------------------------------------------------------------


class TestCmdCheckNoChanges:
    """When there are no staged changes, cmd_check prints a message and exits 0."""

    def test_check_command_no_changes(self, capsys: object) -> None:
        parser = create_parser()
        args = parser.parse_args(["check"])

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value=""),
        ):
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        assert "No changes found" in captured.out


class TestCmdCheckJsonOutput:
    """--json flag produces valid JSON with expected top-level fields."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_check_command_json_output(self, capsys: object) -> None:
        from diff_guard.models import (
            Change,
            ChangeType,
            DownstreamImpact,
            IntendedScope,
            PhantomChange,
            TestSuggestion,
        )

        args = self._make_check_args(["--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=10,
                removed_lines=3,
            ),
        ]
        scope = IntendedScope(
            description="modify app logic",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts={"app"},
            confidence=0.8,
            source="cli",
        )
        phantoms: list[PhantomChange] = []
        downstream: list[DownstreamImpact] = []
        suggestions = [
            TestSuggestion(
                test_file="tests/test_app.py",
                changed_file="src/app.py",
                match_reason="direct name match",
                confidence=0.9,
            ),
        ]

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = phantoms

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = downstream

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.15, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = suggestions

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        assert "changed_files" in output
        assert "intended_scope" in output
        assert "phantom_changes" in output
        assert "downstream_impacts" in output
        assert "risk_score" in output
        assert "risk_level" in output
        assert "suggested_tests" in output
        assert output["risk_level"] == "safe"
        assert output["risk_score"] == 0.15
        assert len(output["changed_files"]) == 1
        assert output["changed_files"][0]["file_path"] == "src/app.py"


class TestCmdCheckScopeFromCli:
    """--scope arg is passed through to ScopeResolver."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_check_command_scope_from_cli(self, capsys: object) -> None:
        from diff_guard.models import (
            Change,
            ChangeType,
            IntendedScope,
        )

        args = self._make_check_args(["--scope", "authentication module", "--json"])

        changes = [
            Change(
                file_path="src/auth.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=1,
            ),
        ]
        scope = IntendedScope(
            description="authentication module",
            target_files={"src/auth.py"},
            target_functions=set(),
            target_concepts={"auth"},
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.2, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        # Verify the scope resolver was called with the CLI scope argument
        mock_scope_resolver.resolve.assert_called_once_with(
            cli_scope="authentication module", changes=changes
        )
        capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0


class TestCmdCheckFailOn:
    """--fail-on flag determines exit code based on risk level."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def _run_check_with_risk(
        self, extra_args: list[str], risk_level: str, scope_confidence: float = 0.8
    ) -> int:
        from diff_guard.models import Change, ChangeType, IntendedScope

        args = self._make_check_args(extra_args + ["--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=10,
                removed_lines=3,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=scope_confidence,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.5, risk_level)

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            return cmd_check(args)

    def test_fail_on_danger_with_danger_returns_1(self) -> None:
        ret = self._run_check_with_risk(["--fail-on", "danger"], "danger")
        assert ret == 1

    def test_fail_on_danger_with_review_returns_0(self) -> None:
        ret = self._run_check_with_risk(["--fail-on", "danger"], "review")
        assert ret == 0

    def test_fail_on_review_with_review_returns_1(self) -> None:
        ret = self._run_check_with_risk(["--fail-on", "review"], "review")
        assert ret == 1

    def test_fail_on_review_with_danger_returns_1(self) -> None:
        ret = self._run_check_with_risk(["--fail-on", "review"], "danger")
        assert ret == 1

    def test_fail_on_safe_returns_1(self) -> None:
        ret = self._run_check_with_risk(["--fail-on", "safe"], "safe")
        assert ret == 1

    def test_fail_on_never_returns_0(self) -> None:
        ret = self._run_check_with_risk(["--fail-on", "never"], "danger")
        assert ret == 0

    def test_no_fail_on_returns_0(self) -> None:
        ret = self._run_check_with_risk([], "danger")
        assert ret == 0

    def test_low_confidence_gates_exit_code(self) -> None:
        """Amendment 6: scope.confidence < 0.4 means always exit 0."""
        ret = self._run_check_with_risk(["--fail-on", "danger"], "danger", scope_confidence=0.3)
        assert ret == 0


class TestCmdCheckDiffSource:
    """Different diff source flags route to the correct parser function."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_last_commit_diff_source(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, IntendedScope

        args = self._make_check_args(["--last-commit", "--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=3,
                removed_lines=1,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_last_commit_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        assert output["risk_level"] == "safe"

    def test_diff_ref_source(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, IntendedScope

        args = self._make_check_args(["--diff", "HEAD~2", "--json"])

        changes = [
            Change(
                file_path="src/utils.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=2,
                removed_lines=0,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/utils.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_diff_from_ref", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        assert output["changed_files"][0]["file_path"] == "src/utils.py"


class TestCmdCheckMarkdownOutput:
    """--markdown flag produces markdown-formatted report."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_check_command_markdown_output(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, IntendedScope

        args = self._make_check_args(["--markdown"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=10,
                removed_lines=3,
            ),
        ]
        scope = IntendedScope(
            description="modify app logic",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts={"app"},
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.15, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        assert "##" in captured.out
        assert "diff-guard Blast Radius Report" in captured.out
        assert "**Risk Level**: safe" in captured.out
        assert "Recommendation" in captured.out


class TestCmdCheckSarifOutput:
    """--sarif flag produces valid SARIF v2.1.0 JSON."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_sarif_output_structure(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, IntendedScope

        args = self._make_check_args(["--sarif"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch(
                "diff_guard.config.find_config",
                return_value=__import__(
                    "diff_guard.models", fromlist=["DiffGuardConfig"]
                ).DiffGuardConfig(),
            ),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
            patch("diff_guard.utils.git.get_staged_commit_message", return_value=""),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert "$schema" in data
        assert data["runs"][0]["tool"]["driver"]["name"] == "diff-guard"


class TestCmdCheckIgnoreFiltering:
    """--ignore flag filters changes in cmd_check."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_ignore_filters_matching_files(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, DiffGuardConfig, IntendedScope

        args = self._make_check_args(["--ignore", "*.lock", "--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
            Change(
                file_path="yarn.lock",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=100,
                removed_lines=50,
            ),
        ]

        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope

        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []

        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []

        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")

        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        config = DiffGuardConfig()

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.config.find_config", return_value=config),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
            patch("diff_guard.utils.git.get_staged_commit_message", return_value=""),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        file_paths = [c["file_path"] for c in output["changed_files"]]
        assert "yarn.lock" not in file_paths
        assert "src/app.py" in file_paths

    def test_all_changes_filtered_returns_early(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, DiffGuardConfig

        args = self._make_check_args(["--ignore", "*.py"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]

        config = DiffGuardConfig()

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.config.find_config", return_value=config),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
        ):
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        assert "All changes filtered" in captured.out


class TestCmdCheckCommitQuality:
    """Commit message quality is wired into the pipeline."""

    def _make_check_args(self, extra: list[str]) -> argparse.Namespace:
        parser = create_parser()
        return parser.parse_args(["check"] + extra)

    def test_commit_quality_attached_to_report(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, DiffGuardConfig, IntendedScope

        args = self._make_check_args(["--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope
        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []
        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []
        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")
        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        config = DiffGuardConfig()

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.config.find_config", return_value=config),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
            patch("diff_guard.utils.git.get_staged_commit_message", return_value="fix"),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        assert "commit_message_quality" in output
        assert output["commit_message_quality"]["is_vague"] is True
        assert output["commit_message_quality"]["score"] < 0.5

    def test_commit_quality_exception_does_not_crash(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, DiffGuardConfig, IntendedScope

        args = self._make_check_args(["--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope
        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []
        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []
        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")
        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        config = DiffGuardConfig()

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.config.find_config", return_value=config),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
            patch(
                "diff_guard.utils.git.get_staged_commit_message", side_effect=OSError("read error")
            ),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        # Pipeline should complete even if commit quality check fails
        assert "changed_files" in output

    def test_empty_commit_message_gives_none_quality(self, capsys: object) -> None:
        from diff_guard.models import Change, ChangeType, DiffGuardConfig, IntendedScope

        args = self._make_check_args(["--json"])

        changes = [
            Change(
                file_path="src/app.py",
                change_type=ChangeType.MODIFIED,
                hunks=[],
                added_lines=5,
                removed_lines=2,
            ),
        ]
        scope = IntendedScope(
            description="test",
            target_files={"src/app.py"},
            target_functions=set(),
            target_concepts=set(),
            confidence=0.8,
            source="cli",
        )

        mock_scope_resolver = MagicMock()
        mock_scope_resolver.resolve.return_value = scope
        mock_phantom_detector = MagicMock()
        mock_phantom_detector.detect.return_value = []
        mock_blast_analyzer = MagicMock()
        mock_blast_analyzer.analyze.return_value = []
        mock_risk_scorer = MagicMock()
        mock_risk_scorer.score.return_value = (0.1, "safe")
        mock_test_mapper = MagicMock()
        mock_test_mapper.map_changes_to_tests.return_value = []

        config = DiffGuardConfig()

        with (
            patch("diff_guard.utils.git.get_repo_root", return_value=Path("/tmp/fake")),
            patch("diff_guard.config.find_config", return_value=config),
            patch("diff_guard.core.diff_parser.get_staged_diff", return_value="not-empty"),
            patch("diff_guard.core.diff_parser.parse_unified_diff", return_value=changes),
            patch("diff_guard.utils.file_graph.FileGraph") as MockFG,
            patch("diff_guard.core.scope_analyzer.ScopeResolver", return_value=mock_scope_resolver),
            patch(
                "diff_guard.core.phantom_change_detector.PhantomChangeDetector",
                return_value=mock_phantom_detector,
            ),
            patch(
                "diff_guard.core.blast_radius.BlastRadiusAnalyzer", return_value=mock_blast_analyzer
            ),
            patch(
                "diff_guard.core.regression_risk_scorer.RegressionRiskScorer",
                return_value=mock_risk_scorer,
            ),
            patch("diff_guard.core.test_mapper.TestMapper", return_value=mock_test_mapper),
            patch("diff_guard.utils.git.get_staged_commit_message", return_value=""),
        ):
            MockFG.return_value.build_cached.return_value = None
            ret = cmd_check(args)

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert ret == 0
        output = json.loads(captured.out)
        assert output["commit_message_quality"] is None

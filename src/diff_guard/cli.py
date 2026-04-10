from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from diff_guard.models import (
    BlastRadiusReport,
    Change,
    CommitMessageQuality,
    DiffGuardConfig,
    IntendedScope,
    TestSuggestion,
)

if TYPE_CHECKING:
    from diff_guard.core.test_mapper import TestMapper


def create_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="diff-guard",
        description="Blast radius analyzer for AI-generated code changes.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # check subcommand
    check_parser = subparsers.add_parser("check", help="Analyze staged changes or last commit")
    check_parser.add_argument("--scope", type=str, default=None, help="Explicit scope description")
    check_parser.add_argument(
        "--staged",
        action="store_true",
        default=True,
        help="Analyze staged changes (default)",
    )
    check_parser.add_argument(
        "--last-commit",
        action="store_true",
        default=False,
        help="Analyze last commit",
    )
    check_parser.add_argument(
        "--diff",
        type=str,
        default=None,
        help="Analyze diff against git ref",
    )
    check_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON",
    )
    check_parser.add_argument(
        "--markdown",
        action="store_true",
        default=False,
        help="Output as markdown",
    )
    check_parser.add_argument(
        "--sarif",
        action="store_true",
        default=False,
        help="Output as SARIF v2.1.0 for CI/CD integration",
    )
    check_parser.add_argument(
        "--fail-on",
        type=str,
        choices=["safe", "review", "danger", "never"],
        default=None,
        help="Exit non-zero if risk reaches this level",
    )
    check_parser.add_argument(
        "--ignore",
        type=str,
        action="append",
        default=[],
        help="Additional ignore patterns",
    )
    check_parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable colored output",
    )

    # test subcommand
    test_parser = subparsers.add_parser("test", help="Suggest tests for staged changes")
    test_parser.add_argument(
        "--staged",
        action="store_true",
        default=True,
        help="Analyze staged changes (default)",
    )
    test_parser.add_argument(
        "--last-commit",
        action="store_true",
        default=False,
        help="Analyze last commit",
    )
    test_parser.add_argument(
        "--diff",
        type=str,
        default=None,
        help="Analyze diff against git ref",
    )
    test_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON",
    )
    test_parser.add_argument(
        "--command-only",
        action="store_true",
        default=False,
        help="Output just the test command",
    )
    test_parser.add_argument(
        "--ignore",
        type=str,
        action="append",
        default=[],
        help="Additional ignore patterns",
    )

    # install subcommand
    install_parser = subparsers.add_parser("install", help="Install as git pre-commit hook")
    install_parser.add_argument(
        "--fail-on",
        type=str,
        choices=["safe", "review", "danger", "never"],
        default="danger",
        help="Hook fail threshold (default: danger)",
    )
    install_parser.add_argument(
        "--mode",
        type=str,
        choices=["test-only", "full", "check-only"],
        default="full",
    )
    install_parser.add_argument(
        "--uninstall",
        action="store_true",
        default=False,
        help="Remove the hook",
    )

    # init subcommand
    subparsers.add_parser("init", help="Create .diff-guard.yml config file")

    return parser


def main() -> None:
    """Entry point for the diff-guard CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "test":
        sys.exit(cmd_test(args))
    elif args.command == "install":
        sys.exit(cmd_install(args))
    elif args.command == "init":
        sys.exit(cmd_init(args))


def cmd_check(args: argparse.Namespace) -> int:
    """Full blast radius analysis of staged changes."""
    from diff_guard.config import find_config
    from diff_guard.core.blast_radius import BlastRadiusAnalyzer
    from diff_guard.core.phantom_change_detector import PhantomChangeDetector
    from diff_guard.core.regression_risk_scorer import RegressionRiskScorer
    from diff_guard.core.scope_analyzer import ScopeResolver
    from diff_guard.core.test_mapper import TestMapper
    from diff_guard.utils.file_graph import FileGraph
    from diff_guard.utils.git import get_repo_root

    repo_root = get_repo_root()
    config = find_config(repo_root)

    changes = _parse_and_filter_changes(args, repo_root, config)
    if changes is None:
        return 0

    commit_quality = _check_commit_quality(repo_root, changes)

    file_graph = FileGraph(repo_root)
    file_graph.build_cached()

    cli_scope: str | None = getattr(args, "scope", None)
    scope_resolver = ScopeResolver(repo_root, config=config)
    scope = scope_resolver.resolve(cli_scope=cli_scope, changes=changes)

    phantom_detector = PhantomChangeDetector(file_graph=file_graph, config=config)
    phantoms = phantom_detector.detect(changes, scope)

    blast_analyzer = BlastRadiusAnalyzer(file_graph)
    downstream = blast_analyzer.analyze(changes, scope)

    risk_scorer = RegressionRiskScorer(file_graph=file_graph, config=config)
    risk_score, risk_level = risk_scorer.score(changes, scope, phantoms, downstream)

    test_mapper = TestMapper(repo_root, file_graph=file_graph, config=config.tests)
    suggested_tests = test_mapper.map_changes_to_tests(changes)

    report = BlastRadiusReport(
        changed_files=changes,
        intended_scope=scope,
        phantom_changes=phantoms,
        downstream_impacts=downstream,
        risk_score=risk_score,
        risk_level=risk_level,
        suggested_tests=suggested_tests,
        commit_message_quality=commit_quality,
    )

    rendered = _render_report(args, report)
    if rendered is not None:
        print(rendered)

    return _exit_code_for_fail_on(args, scope, risk_level)


def cmd_test(args: argparse.Namespace) -> int:
    """Handle 'diff-guard test' -- suggest tests for staged changes."""
    from diff_guard.config import find_config
    from diff_guard.core.test_mapper import TestMapper
    from diff_guard.utils.file_graph import FileGraph
    from diff_guard.utils.git import get_repo_root

    repo_root = get_repo_root()
    config = find_config(repo_root)

    changes = _parse_and_filter_changes(args, repo_root, config)
    if changes is None:
        return 0

    file_graph = FileGraph(repo_root)
    file_graph.build_cached()

    mapper = TestMapper(repo_root, file_graph=file_graph, config=config.tests)
    suggestions = mapper.map_changes_to_tests(changes)

    if getattr(args, "command_only", False):
        command = mapper.suggest_test_command(suggestions)
        if command:
            print(command)
        return 0

    if getattr(args, "json", False):
        _print_test_json(changes, suggestions, mapper)
        return 0

    _print_test_human(changes, suggestions, mapper)
    return 0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CHANGE_MESSAGES = {
    "empty": "No changes found.",
    "filtered": "All changes filtered by ignore patterns.",
}


def _matches_ignore_pattern(file_path: str, pattern: str) -> bool:
    """Check if a file path matches an ignore pattern.

    Directory patterns ending with ``/`` match any file within that directory.
    Other patterns use standard glob matching via :mod:`fnmatch`.
    """
    if pattern.endswith("/"):
        return file_path.startswith(pattern) or file_path.startswith(pattern.rstrip("/"))
    return fnmatch.fnmatch(file_path, pattern)


def _parse_and_filter_changes(
    args: argparse.Namespace,
    repo_root: Path | None,
    config: DiffGuardConfig,
) -> list[Change] | None:
    """Parse diff from the appropriate source and apply ignore filters.

    Returns ``None`` (and prints a message) when there are no changes to analyze.
    """
    from diff_guard.core.diff_parser import (
        parse_diff_from_ref,
        parse_last_commit,
        parse_staged_diff,
    )

    if getattr(args, "last_commit", False):
        changes = parse_last_commit(repo_root)
    elif getattr(args, "diff", None) is not None:
        changes = parse_diff_from_ref(args.diff, repo_root)
    else:
        changes = parse_staged_diff(repo_root)

    if not changes:
        print(_CHANGE_MESSAGES["empty"])
        return None

    ignore_patterns = list(config.ignore) + list(getattr(args, "ignore", []))
    if ignore_patterns:
        changes = [
            c
            for c in changes
            if not any(_matches_ignore_pattern(c.file_path, pat) for pat in ignore_patterns)
        ]

    if not changes:
        print(_CHANGE_MESSAGES["filtered"])
        return None

    return changes


def _check_commit_quality(
    repo_root: Path | None, changes: list[Change]
) -> CommitMessageQuality | None:
    """Best-effort commit message quality check."""
    try:
        from diff_guard.core.commit_message_checker import check_commit_message
        from diff_guard.utils.git import get_staged_commit_message

        commit_msg = get_staged_commit_message(repo_root)
        if commit_msg:
            return check_commit_message(commit_msg, changes)
    except (ImportError, OSError, ValueError):
        pass  # Best-effort, don't block the pipeline
    return None


def _render_report(args: argparse.Namespace, report: BlastRadiusReport) -> str | None:
    """Select and run the appropriate reporter based on CLI flags."""
    if getattr(args, "sarif", False):
        from diff_guard.reporters.sarif_reporter import SARIFReporter

        return SARIFReporter().render_report(report)
    if getattr(args, "json", False):
        from diff_guard.reporters.json_reporter import JSONReporter

        return JSONReporter().render_report(report)
    if getattr(args, "markdown", False):
        from diff_guard.reporters.markdown_reporter import MarkdownReporter

        return MarkdownReporter().render_report(report)

    from diff_guard.reporters.terminal_reporter import TerminalReporter

    no_color: bool = getattr(args, "no_color", False)
    return TerminalReporter(no_color=no_color).render_report(report)


def _exit_code_for_fail_on(
    args: argparse.Namespace,
    scope: IntendedScope,
    risk_level: str,
) -> int:
    """Determine exit code based on --fail-on and scope confidence."""
    fail_on: str | None = getattr(args, "fail_on", None)

    if scope.confidence < 0.4:
        return 0

    if fail_on == "safe":
        return 1
    if fail_on == "review" and risk_level in ("review", "danger"):
        return 1
    if fail_on == "danger" and risk_level == "danger":
        return 1

    return 0


def _print_test_json(
    changes: list[Change],
    suggestions: list[TestSuggestion],
    mapper: TestMapper,
) -> None:
    """Print test suggestions as JSON."""
    output = {
        "changed_files": [
            {
                "path": c.file_path,
                "type": c.change_type.value,
                "added_lines": c.added_lines,
                "removed_lines": c.removed_lines,
            }
            for c in changes
        ],
        "test_suggestions": [asdict(s) for s in suggestions],
        "test_command": mapper.suggest_test_command(suggestions),
    }
    print(json.dumps(output, indent=2))


def _print_test_human(
    changes: list[Change],
    suggestions: list[TestSuggestion],
    mapper: TestMapper,
) -> None:
    """Print test suggestions in human-readable format."""
    print("Changed files and suggested tests:\n")
    for change in changes:
        print(f"  {change.file_path} ({change.change_type.value})")
        matching = [s for s in suggestions if s.changed_file == change.file_path]
        if matching:
            for sug in matching:
                print(
                    f"    -> {sug.test_file} ({sug.match_reason}, confidence: {sug.confidence:.1f})"
                )
        else:
            print("    -> no test files found")
        print()

    command = mapper.suggest_test_command(suggestions)
    if command:
        print(f"Suggested test command:\n  {command}")
    else:
        print("No test files found for the changed files.")


def cmd_install(args: argparse.Namespace) -> int:
    """Handle 'diff-guard install' -- install git pre-commit hook."""
    from diff_guard.hooks.install import install_hook, uninstall_hook

    if getattr(args, "uninstall", False):
        if uninstall_hook():
            print("Uninstalled diff-guard pre-commit hook")
            return 0
        print("diff-guard hook not found")
        return 1

    path = install_hook(fail_on=args.fail_on, mode=args.mode)
    print(f"Installed diff-guard as pre-commit hook in {path}")
    print("   Every commit will be checked. Use --no-verify to skip.")
    print("   Configure behavior in .diff-guard.yml")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Create .diff-guard.yml config file with sensible defaults."""
    from diff_guard.config import generate_default_config
    from diff_guard.utils.git import get_repo_root

    repo_root = get_repo_root()
    config_path = repo_root / ".diff-guard.yml"

    if config_path.exists():
        print(f"Configuration file already exists: {config_path}")
        print("Remove it first if you want to regenerate defaults.")
        return 1

    config_path.write_text(generate_default_config())
    print(f"Created {config_path} with default configuration")
    return 0

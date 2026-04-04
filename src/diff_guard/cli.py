from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def create_parser() -> argparse.ArgumentParser:
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
    from diff_guard.core.blast_radius import BlastRadiusAnalyzer
    from diff_guard.core.diff_parser import (
        parse_diff_from_ref,
        parse_last_commit,
        parse_staged_diff,
    )
    from diff_guard.core.phantom_change_detector import PhantomChangeDetector
    from diff_guard.core.regression_risk_scorer import RegressionRiskScorer
    from diff_guard.core.scope_analyzer import ScopeResolver
    from diff_guard.core.test_mapper import TestMapper
    from diff_guard.models import BlastRadiusReport
    from diff_guard.utils.file_graph import FileGraph
    from diff_guard.utils.git import get_repo_root

    repo_root = get_repo_root()

    # 1. Determine diff source
    if getattr(args, "last_commit", False):
        changes = parse_last_commit(repo_root)
    elif getattr(args, "diff", None) is not None:
        changes = parse_diff_from_ref(args.diff, repo_root)
    else:
        changes = parse_staged_diff(repo_root)

    # 2. No changes
    if not changes:
        print("No changes found.")
        return 0

    # 3. Build FileGraph
    file_graph = FileGraph(repo_root)
    file_graph.build()

    # 4. Resolve scope
    cli_scope: str | None = getattr(args, "scope", None)
    scope_resolver = ScopeResolver(repo_root)
    scope = scope_resolver.resolve(cli_scope=cli_scope, changes=changes)

    # 5. Detect phantom changes
    phantom_detector = PhantomChangeDetector(file_graph=file_graph)
    phantoms = phantom_detector.detect(changes, scope)

    # 6. Compute blast radius
    blast_analyzer = BlastRadiusAnalyzer(file_graph)
    downstream = blast_analyzer.analyze(changes, scope)

    # 7. Score regression risk
    risk_scorer = RegressionRiskScorer(file_graph=file_graph)
    risk_score, risk_level = risk_scorer.score(changes, scope, phantoms, downstream)

    # 8. Map tests
    test_mapper = TestMapper(repo_root, file_graph=file_graph)
    suggested_tests = test_mapper.map_changes_to_tests(changes)

    # 9. Assemble report
    report = BlastRadiusReport(
        changed_files=changes,
        intended_scope=scope,
        phantom_changes=phantoms,
        downstream_impacts=downstream,
        risk_score=risk_score,
        risk_level=risk_level,
        suggested_tests=suggested_tests,
    )

    # 10. Render output
    rendered: str | None = None
    if getattr(args, "json", False):
        from diff_guard.reporters.json_reporter import JSONReporter

        json_reporter = JSONReporter()
        rendered = json_reporter.render_report(report)
    elif getattr(args, "markdown", False):
        from diff_guard.reporters.markdown_reporter import MarkdownReporter

        md_reporter = MarkdownReporter()
        rendered = md_reporter.render_report(report)
    else:
        from diff_guard.reporters.terminal_reporter import TerminalReporter

        no_color: bool = getattr(args, "no_color", False)
        term_reporter = TerminalReporter(no_color=no_color)
        rendered = term_reporter.render_report(report)

    if rendered is not None:
        print(rendered)

    # 11. Determine exit code
    fail_on: str | None = getattr(args, "fail_on", None)

    # Amendment 6: if scope confidence < 0.4, never exit non-zero
    if scope.confidence < 0.4:
        return 0

    if fail_on == "safe":
        return 1
    if fail_on == "review" and risk_level in ("review", "danger"):
        return 1
    if fail_on == "danger" and risk_level == "danger":
        return 1

    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Handle 'diff-guard test' -- suggest tests for staged changes."""
    from diff_guard.core.diff_parser import (
        parse_diff_from_ref,
        parse_last_commit,
        parse_staged_diff,
    )
    from diff_guard.core.test_mapper import TestMapper
    from diff_guard.utils.file_graph import FileGraph
    from diff_guard.utils.git import get_repo_root

    repo_root = get_repo_root()

    # 1. Determine diff source
    if getattr(args, "last_commit", False):
        changes = parse_last_commit(repo_root)
    elif getattr(args, "diff", None) is not None:
        changes = parse_diff_from_ref(args.diff, repo_root)
    else:
        changes = parse_staged_diff(repo_root)

    # 2. No changes
    if not changes:
        print("No changes found.")
        return 0

    # 3. Build FileGraph
    file_graph = FileGraph(repo_root)
    file_graph.build()

    # 4. Create TestMapper
    mapper = TestMapper(repo_root, file_graph=file_graph)

    # 5. Map changes to tests
    suggestions = mapper.map_changes_to_tests(changes)

    # 6. --command-only
    if getattr(args, "command_only", False):
        command = mapper.suggest_test_command(suggestions)
        if command:
            print(command)
        return 0

    # 7. --json
    if getattr(args, "json", False):
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
        return 0

    # 8. Human-readable output
    print("Changed files and suggested tests:\n")
    for change in changes:
        print(f"  {change.file_path} ({change.change_type.value})")
        matching = [s for s in suggestions if s.changed_file == change.file_path]
        if matching:
            for sug in matching:
                print(
                    f"    -> {sug.test_file} "
                    f"({sug.match_reason}, confidence: {sug.confidence:.1f})"
                )
        else:
            print("    -> no test files found")
        print()

    command = mapper.suggest_test_command(suggestions)
    if command:
        print(f"Suggested test command:\n  {command}")
    else:
        print("No test files found for the changed files.")

    return 0


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

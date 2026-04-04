from __future__ import annotations

import os
import sys

from diff_guard.models import (
    BlastRadiusReport,
    Change,
    DownstreamImpact,
    IntendedScope,
    PhantomChange,
    TestSuggestion,
)


class TerminalReporter:
    """ANSI-colored terminal output with box-drawing characters."""

    # ANSI codes
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    # Box-drawing characters
    TOP_LEFT = "\u256d"
    TOP_RIGHT = "\u256e"
    BOTTOM_LEFT = "\u2570"
    BOTTOM_RIGHT = "\u256f"
    HORIZONTAL = "\u2500"
    VERTICAL = "\u2502"
    TEE_RIGHT = "\u251c"
    TEE_LEFT = "\u2524"

    # Tree characters
    TREE_TEE = "\u251c\u2500\u2500 "
    TREE_LAST = "\u2514\u2500\u2500 "

    def __init__(self, no_color: bool = False) -> None:
        self.no_color = no_color or bool(os.environ.get("NO_COLOR"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_report(self, report: BlastRadiusReport) -> str:
        """Render the full blast radius report."""
        total_added = sum(c.added_lines for c in report.changed_files)
        total_removed = sum(c.removed_lines for c in report.changed_files)

        sections: list[str] = []

        sections.append(
            self.render_header(
                report.intended_scope,
                len(report.changed_files),
                total_added,
                total_removed,
            )
        )

        sections.append(
            self.render_risk_gauge(report.risk_score, report.risk_level)
        )

        sections.append(
            self.render_in_scope(report.changed_files, report.intended_scope)
        )

        if report.phantom_changes:
            sections.append(
                self.render_phantom_changes(report.phantom_changes)
            )

        if report.downstream_impacts:
            sections.append(
                self.render_blast_radius(report.downstream_impacts)
            )

        command = self._build_test_command(report.suggested_tests)
        sections.append(
            self.render_test_suggestions(report.suggested_tests, command)
        )

        sections.append(self.render_recommendation(report))

        return "\n\n".join(sections) + "\n"

    def render_header(
        self,
        scope: IntendedScope,
        file_count: int,
        added: int,
        removed: int,
    ) -> str:
        """Render the top box with scope summary."""
        title = "diff-guard blast radius"

        risk_level_map: dict[str, tuple[str, str]] = {
            "safe": (self.GREEN, "SAFE"),
            "review": (self.YELLOW, "REVIEW"),
            "danger": (self.RED, "DANGER"),
        }
        color, label = risk_level_map.get(
            scope.source, (self.YELLOW, scope.source.upper())
        )
        # For header we re-derive risk from the scope param – callers
        # typically pass a full report; here we accept separate params.
        # We use a reasonable default.

        lines: list[str] = []
        lines.append(title.center(58))
        lines.append("")
        scope_text = f'Scope: "{scope.description}"'
        if len(scope_text) > 58:
            scope_text = scope_text[:55] + "..."
        lines.append(scope_text)
        lines.append(
            f"Files changed: {file_count}  |  Lines: +{added} / -{removed}"
        )

        return self._box(lines, width=60)

    def render_risk_gauge(self, score: float, level: str) -> str:
        """Render a visual risk gauge using block characters."""
        filled = "\u2588"
        empty = "\u2591"
        bar_width = 20
        filled_count = max(0, min(bar_width, int(round(score * bar_width))))
        empty_count = bar_width - filled_count

        bar_raw = filled * filled_count + empty * empty_count

        color_map: dict[str, str] = {
            "safe": self.GREEN,
            "review": self.YELLOW,
            "danger": self.RED,
        }
        color = color_map.get(level, self.YELLOW)

        level_map: dict[str, str] = {
            "safe": "SAFE",
            "review": "REVIEW",
            "danger": "DANGER",
        }
        level_label = level_map.get(level, level.upper())

        icon_map: dict[str, str] = {
            "safe": "\u2705",       # check mark
            "review": "\u26a0\ufe0f",  # warning
            "danger": "\U0001f4a5",   # collision
        }
        icon = icon_map.get(level, "")

        bar_colored = self._color(bar_raw, color)
        gauge_line = f"Risk level: {icon}  {self._color(level_label, color)} (score: {score:.2f})"
        bar_line = f"  [{bar_colored}] {score:.0%}"

        return gauge_line + "\n" + bar_line

    def render_in_scope(
        self, changes: list[Change], scope: IntendedScope
    ) -> str:
        """Render green section: files within scope."""
        in_scope = [
            c
            for c in changes
            if c.file_path in scope.target_files
        ]
        if not in_scope:
            # If no explicit target files, treat all changed files as in-scope
            in_scope = list(changes)

        header = self._color(
            f"\u2705 In scope ({len(in_scope)} file{'s' if len(in_scope) != 1 else ''}):",
            self.GREEN,
        )
        lines: list[str] = [header]

        for change in in_scope:
            funcs = ", ".join(change.functions_modified) if change.functions_modified else ""
            line = f"   {change.file_path:<28} +{change.added_lines} / -{change.removed_lines}"
            if funcs:
                line += f"   {funcs}"
            lines.append(line)

        return "\n".join(lines)

    def render_phantom_changes(self, phantoms: list[PhantomChange]) -> str:
        """Render yellow/red section with confidence display."""
        count_label = "file" if len(phantoms) == 1 else "files"
        header = self._color(
            f"\u26a0\ufe0f  Phantom changes "
            f"({len(phantoms)} {count_label}):",
            self.YELLOW,
        )
        lines: list[str] = [header]

        for phantom in phantoms:
            severity_color = self.YELLOW if phantom.severity in ("info", "warning") else self.RED
            line = (
                f"   {phantom.file_path:<28}"
                f"+{phantom.added_lines} / -{phantom.removed_lines}"
                f"    [confidence: {phantom.confidence:.0%}]"
            )
            lines.append(self._color(line, severity_color))
            lines.append(f"   \u2502  \u2192 {phantom.reason}")

        return "\n".join(lines)

    def render_blast_radius(self, impacts: list[DownstreamImpact]) -> str:
        """Render tree view of downstream affected files."""
        header = self._color(
            "\U0001f4a5 Downstream blast radius:",
            self.RED,
        )
        lines: list[str] = [header]

        sorted_impacts = sorted(impacts, key=lambda i: i.distance)

        for idx, impact in enumerate(sorted_impacts):
            is_last = idx == len(sorted_impacts) - 1
            prefix = self.TREE_LAST if is_last else self.TREE_TEE
            via = " -> ".join(impact.via_files) if impact.via_files else ""
            dist_label = f"{impact.distance}-hop" if impact.distance > 1 else "direct"
            line = f"   {prefix}{impact.file_path:<28} {dist_label}"
            if via:
                line += f"  via {via}"
            lines.append(line)

        return "\n".join(lines)

    def render_test_suggestions(
        self, suggestions: list[TestSuggestion], command: str
    ) -> str:
        """Render test command and file mapping."""
        header = "\U0001f9ea Suggested tests to run:"
        lines: list[str] = [header]

        if command:
            lines.append(f"   {command}")
        elif suggestions:
            test_files = sorted({s.test_file for s in suggestions})
            lines.append(f"   pytest {' '.join(test_files)} -v")
        else:
            lines.append("   No test files found.")

        if suggestions:
            lines.append("")
            for sug in suggestions:
                lines.append(
                    f"   {sug.test_file:<32} <- {sug.changed_file}  ({sug.match_reason})"
                )

        return "\n".join(lines)

    def render_recommendation(self, report: BlastRadiusReport) -> str:
        """Render the final recommendation line."""
        if report.risk_level == "safe":
            rec = "Changes look safe and within scope."
            icon = "\U0001f4a1"
        elif report.risk_level == "review":
            phantom_files = [p.file_path for p in report.phantom_changes]
            if phantom_files:
                files_str = " and ".join(phantom_files[:3])
                rec = f"Review changes to {files_str} manually."
            else:
                rec = "Review changes before committing."
            icon = "\U0001f4a1"
        else:
            rec = "High risk! Consider splitting changes into smaller commits."
            icon = "\u2757"

        result = f"{icon} Recommendation: {rec}"
        # Truncate to ~80 characters if needed
        if len(result) > 90:
            result = result[:87] + "..."
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _color(self, text: str, color: str) -> str:
        """Wrap text in ANSI color codes."""
        if self.no_color or not self._supports_color():
            return text
        return f"{color}{text}{self.RESET}"

    def _box(self, lines: list[str], width: int = 60) -> str:
        """Draw a box using Unicode box-drawing characters."""
        inner_width = width - 2  # subtract the two vertical bars

        top = (
            self.TOP_LEFT
            + self.HORIZONTAL * inner_width
            + self.TOP_RIGHT
        )
        bottom = (
            self.BOTTOM_LEFT
            + self.HORIZONTAL * inner_width
            + self.BOTTOM_RIGHT
        )
        tee = (
            self.TEE_RIGHT
            + self.HORIZONTAL * inner_width
            + self.TEE_LEFT
        )

        boxed_lines: list[str] = [top]
        for i, line in enumerate(lines):
            padded = line[:inner_width].center(inner_width)
            boxed_lines.append(f"{self.VERTICAL}{padded}{self.VERTICAL}")
            # Insert tee separator after title line (first non-empty line)
            if i == 0 and len(lines) > 1:
                boxed_lines.append(tee)
        boxed_lines.append(bottom)

        return "\n".join(boxed_lines)

    def _supports_color(self) -> bool:
        """Check if terminal supports ANSI colors."""
        if self.no_color:
            return False
        if not hasattr(sys.stdout, "isatty"):
            return False
        return sys.stdout.isatty()

    def _build_test_command(self, suggestions: list[TestSuggestion]) -> str:
        """Build a pytest command from test suggestions."""
        if not suggestions:
            return ""
        test_files = sorted({s.test_file for s in suggestions})
        return f"pytest {' '.join(test_files)} -v"

from __future__ import annotations

from diff_guard.models import BlastRadiusReport


class MarkdownReporter:
    """Markdown output for PR comments."""

    def render_report(self, report: BlastRadiusReport) -> str:
        """Render report as markdown with sections."""
        lines: list[str] = []

        # Header
        lines.append("## :shield: diff-guard Blast Radius Report")
        lines.append("")

        # Summary
        scope_desc = report.intended_scope.description or "N/A"
        conf = report.intended_scope.confidence
        lines.append(
            f"**Scope**: {scope_desc} _(confidence: {conf:.2f})_"
        )
        lines.append(f"**Risk Level**: {report.risk_level} (score: {report.risk_score:.2f})")
        lines.append("")

        # In Scope
        scope_files = sorted(report.intended_scope.target_files)
        lines.append(f"### :white_check_mark: In Scope ({len(scope_files)} files)")
        lines.append("")
        if scope_files:
            for f in scope_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("_No files in scope._")
        lines.append("")

        # Changed Files
        lines.append(f"### :page_facing_up: Changed Files ({len(report.changed_files)})")
        lines.append("")
        if report.changed_files:
            for c in report.changed_files:
                ct = c.change_type.value
                lines.append(
                    f"- `{c.file_path}` ({ct}, "
                    f"+{c.added_lines}/-{c.removed_lines})"
                )
        else:
            lines.append("_No changes._")
        lines.append("")

        # Phantom Changes
        phantom_count = len(report.phantom_changes)
        lines.append(f"### :ghost: Phantom Changes ({phantom_count} files)")
        lines.append("")
        if report.phantom_changes:
            for p in report.phantom_changes:
                lines.append(
                    f"- `{p.file_path}` [{p.severity}] {p.reason} "
                    f"(+{p.added_lines}/-{p.removed_lines})"
                )
        else:
            lines.append("_No phantom changes detected._")
        lines.append("")

        # Downstream Impact
        downstream_count = len(report.downstream_impacts)
        lines.append(f"### :link: Downstream Impact ({downstream_count} files)")
        lines.append("")
        if report.downstream_impacts:
            for d in report.downstream_impacts:
                via = " -> ".join(d.via_files)
                lines.append(
                    f"- `{d.file_path}` (distance: {d.distance}, "
                    f"risk: {d.risk_contribution:.2f}, via: {via})"
                )
        else:
            lines.append("_No downstream impact detected._")
        lines.append("")

        # Suggested Tests
        test_count = len(report.suggested_tests)
        lines.append(f"### :test_tube: Suggested Tests ({test_count})")
        lines.append("")
        if report.suggested_tests:
            for t in report.suggested_tests:
                lines.append(
                    f"- `{t.test_file}` for `{t.changed_file}` "
                    f"({t.match_reason}, confidence: {t.confidence:.1f})"
                )
        else:
            lines.append("_No test suggestions._")
        lines.append("")

        # Recommendation
        lines.append("### :bulb: Recommendation")
        lines.append("")
        if report.risk_level == "safe":
            lines.append("Changes appear safe and within scope. Proceed with confidence.")
        elif report.risk_level == "review":
            lines.append(
                "Some concerns detected. Consider reviewing phantom changes "
                "and downstream impacts before proceeding."
            )
        else:
            lines.append(
                "**High risk detected.** Significant blast radius or phantom changes. "
                "Strongly recommend thorough review and testing before committing."
            )
        lines.append("")

        return "\n".join(lines)

"""SARIF v2.1.0 reporter for CI/CD integration.

Produces output compatible with GitHub Code Scanning, Azure DevOps,
and other SARIF-consuming platforms.
"""

from __future__ import annotations

import json

from diff_guard.models import BlastRadiusReport


class SARIFReporter:
    """Render blast radius report as SARIF v2.1.0 JSON."""

    def render_report(self, report: BlastRadiusReport) -> str:
        """Render report as SARIF v2.1.0 JSON string."""
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "diff-guard",
                            "version": "0.3.0",
                            "informationUri": "https://github.com/shivamjohri/diff-guard",
                            "rules": self._build_rules(),
                        }
                    },
                    "results": self._build_results(report),
                }
            ],
        }
        return json.dumps(sarif, indent=2)

    def _build_rules(self) -> list[dict]:
        return [
            {
                "id": "DG001",
                "name": "PhantomChange",
                "shortDescription": {"text": "Change detected outside the intended scope"},
                "defaultConfiguration": {"level": "warning"},
            },
            {
                "id": "DG002",
                "name": "HighBlastRadius",
                "shortDescription": {"text": "Significant downstream impact detected"},
                "defaultConfiguration": {"level": "note"},
            },
            {
                "id": "DG003",
                "name": "RegressionRisk",
                "shortDescription": {"text": "High regression risk score"},
                "defaultConfiguration": {"level": "warning"},
            },
            {
                "id": "DG004",
                "name": "CommitMessageQuality",
                "shortDescription": {"text": "Low quality or vague commit message"},
                "defaultConfiguration": {"level": "note"},
            },
        ]

    def _build_results(self, report: BlastRadiusReport) -> list[dict]:
        results: list[dict] = []
        results.extend(self._phantom_change_results(report))
        results.extend(self._downstream_impact_results(report))
        results.extend(self._regression_risk_results(report))
        results.extend(self._commit_quality_results(report))
        return results

    def _phantom_change_results(self, report: BlastRadiusReport) -> list[dict]:
        """DG001: Changes detected outside the intended scope."""
        results: list[dict] = []
        for phantom in report.phantom_changes:
            level = {
                "info": "note",
                "warning": "warning",
                "critical": "error",
            }.get(phantom.severity, "warning")

            results.append(
                {
                    "ruleId": "DG001",
                    "level": level,
                    "message": {
                        "text": f"{phantom.reason} (relevance: {phantom.relevance_score:.2f})"
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": phantom.file_path},
                            }
                        }
                    ],
                    "properties": {
                        "addedLines": phantom.added_lines,
                        "removedLines": phantom.removed_lines,
                        "confidence": phantom.confidence,
                    },
                }
            )
        return results

    def _downstream_impact_results(self, report: BlastRadiusReport) -> list[dict]:
        """DG002: Files affected through the import/dependency chain."""
        results: list[dict] = []
        for impact in report.downstream_impacts:
            results.append(
                {
                    "ruleId": "DG002",
                    "level": "warning" if impact.distance == 1 else "note",
                    "message": {
                        "text": (
                            f"Downstream impact: {impact.distance}-hop away, "
                            f"risk contribution: {impact.risk_contribution:.2f}"
                        )
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": impact.file_path},
                            }
                        }
                    ],
                }
            )
        return results

    def _regression_risk_results(self, report: BlastRadiusReport) -> list[dict]:
        """DG003: Overall regression risk when elevated."""
        if report.risk_level not in ("review", "danger"):
            return []
        return [
            {
                "ruleId": "DG003",
                "level": "error" if report.risk_level == "danger" else "warning",
                "message": {
                    "text": (
                        f"Overall regression risk: {report.risk_level}"
                        f" (score: {report.risk_score:.2f})"
                    )
                },
            }
        ]

    def _commit_quality_results(self, report: BlastRadiusReport) -> list[dict]:
        """DG004: Low quality or vague commit message."""
        quality = report.commit_message_quality
        if not quality or quality.score >= 0.5:
            return []
        return [
            {
                "ruleId": "DG004",
                "level": "warning",
                "message": {
                    "text": (
                        f"Commit message quality: {quality.score:.0%}. " + "; ".join(quality.issues)
                    )
                },
                "properties": {
                    "isVague": quality.is_vague,
                    "suggestedImprovement": quality.suggested_improvement,
                },
            }
        ]

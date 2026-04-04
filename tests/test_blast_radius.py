from __future__ import annotations

from pathlib import Path

import pytest

from diff_guard.core.blast_radius import BlastRadiusAnalyzer
from diff_guard.models import Change, ChangeType, Hunk, IntendedScope
from diff_guard.utils.file_graph import FileGraph


@pytest.fixture
def graph(simple_python_project: Path) -> FileGraph:
    g = FileGraph(simple_python_project)
    g.build()
    return g


@pytest.fixture
def analyzer(graph: FileGraph) -> BlastRadiusAnalyzer:
    return BlastRadiusAnalyzer(graph)


def _change(file_path: str) -> Change:
    return Change(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        hunks=[Hunk(1, 1, 1, 1, "")],
        added_lines=1,
        removed_lines=1,
    )


class TestDirectDependents:
    """Changing session.py impacts users.py, dashboard.py, stripe.py (1-hop)."""

    def test_direct_dependents(self, analyzer: BlastRadiusAnalyzer, graph: FileGraph) -> None:
        results = analyzer.find_all_downstream(["auth/session.py"], max_depth=1)
        impacted = {r.file_path for r in results}
        assert "api/users.py" in impacted
        assert "api/dashboard.py" in impacted
        assert "payments/stripe.py" in impacted


class TestTransitiveDependents:
    """Changing validators.py impacts files depending on files importing validators."""

    def test_transitive_dependents(self, analyzer: BlastRadiusAnalyzer) -> None:
        results = analyzer.find_all_downstream(["utils/validators.py"], max_depth=2)
        impacted = {r.file_path for r in results}
        # Direct dependents (1-hop): auth/session.py, auth/login.py, payments/stripe.py
        assert "auth/session.py" in impacted
        assert "auth/login.py" in impacted
        assert "payments/stripe.py" in impacted
        # Transitive dependents (2-hop): files that depend on auth/session.py
        assert "api/users.py" in impacted
        assert "api/dashboard.py" in impacted


class TestDistanceScoring:
    """1-hop dependents have higher risk than 2-hop dependents."""

    def test_distance_scoring(self, analyzer: BlastRadiusAnalyzer) -> None:
        results = analyzer.find_all_downstream(["utils/validators.py"], max_depth=3)
        by_file = {r.file_path: r for r in results}
        # auth/session.py is 1-hop -> distance=1
        assert by_file["auth/session.py"].distance == 1
        # api/users.py is reachable via auth/session.py -> distance=2
        assert by_file["api/users.py"].distance == 2
        # 1-hop risk should be higher than 2-hop risk
        assert by_file["auth/session.py"].risk_contribution > by_file["api/users.py"].risk_contribution


class TestExcludesChangedFiles:
    """Files in the change set are not listed as downstream impacts."""

    def test_excludes_changed_files(self, analyzer: BlastRadiusAnalyzer) -> None:
        # Change both session.py and users.py
        results = analyzer.find_all_downstream(
            ["auth/session.py", "api/users.py"], max_depth=2
        )
        impacted = {r.file_path for r in results}
        # The changed files themselves should not appear as downstream impacts
        assert "auth/session.py" not in impacted
        assert "api/users.py" not in impacted


class TestMaxDepth:
    """Respects max_depth parameter."""

    def test_max_depth(self, analyzer: BlastRadiusAnalyzer) -> None:
        # With max_depth=1, only direct dependents of validators.py appear
        results_1 = analyzer.find_all_downstream(["utils/validators.py"], max_depth=1)
        impacted_1 = {r.file_path for r in results_1}
        assert "auth/session.py" in impacted_1
        # api/users.py is 2 hops away, should not appear at max_depth=1
        assert "api/users.py" not in impacted_1

        # With max_depth=2, api/users.py should appear
        results_2 = analyzer.find_all_downstream(["utils/validators.py"], max_depth=2)
        impacted_2 = {r.file_path for r in results_2}
        assert "api/users.py" in impacted_2


class TestDeduplication:
    """File reachable via multiple paths appears once with highest score."""

    def test_deduplication(self, analyzer: BlastRadiusAnalyzer) -> None:
        # Change both validators.py and session.py
        # api/users.py is reachable via:
        #   validators.py -> session.py -> users.py (distance 2)
        #   session.py -> users.py (distance 1)
        results = analyzer.find_all_downstream(
            ["utils/validators.py", "auth/session.py"], max_depth=3
        )
        users_results = [r for r in results if r.file_path == "api/users.py"]
        # Should appear only once
        assert len(users_results) == 1
        # Should have the higher risk score (via the shorter path from session.py)
        assert users_results[0].distance == 1

from __future__ import annotations

from collections import deque

from diff_guard.models import Change, DownstreamImpact, IntendedScope
from diff_guard.utils.file_graph import FileGraph

# Distance -> risk factor mapping
_DISTANCE_SCORES: dict[int, float] = {
    1: 0.8,
    2: 0.4,
    3: 0.1,
}


class BlastRadiusAnalyzer:
    """Compute downstream impact of changes."""

    def __init__(self, file_graph: FileGraph) -> None:
        self.file_graph = file_graph

    def analyze(
        self, changes: list[Change], scope: IntendedScope
    ) -> list[DownstreamImpact]:
        """For each changed file, find downstream dependents not in the change set."""
        changed_paths: list[str] = [c.file_path for c in changes]
        raw = self.find_all_downstream(changed_paths)
        # Exclude files already covered by the intended scope
        scope_files = scope.target_files
        return [imp for imp in raw if imp.file_path not in scope_files]

    def find_all_downstream(
        self, changed_files: list[str], max_depth: int = 3
    ) -> list[DownstreamImpact]:
        """BFS from each changed file, collect downstream dependents up to max_depth."""
        changed_set: set[str] = set(changed_files)

        # Compute max centrality for normalisation
        all_files = list(self.file_graph._forward.keys())
        max_centrality: int = 1
        for f in all_files:
            c = self.file_graph.centrality(f)
            if c > max_centrality:
                max_centrality = c

        # Collect (file_path, distance, via_files) tuples via BFS
        # Use a dict keyed by file_path -> best DownstreamImpact so far
        best: dict[str, DownstreamImpact] = {}

        for src in changed_files:
            # BFS over *reverse* edges (dependents) starting from src
            visited: set[str] = {src}
            queue: deque[tuple[str, int, list[str]]] = deque(
                [(src, 0, [src])]
            )

            while queue:
                current, dist, path = queue.popleft()
                if dist > 0:
                    # current is a downstream dependent of src
                    if current not in changed_set:
                        d_factor = self.score_distance(dist)
                        c_factor = self.score_centrality(current)
                        # Normalise centrality factor by max_centrality
                        norm_centrality = c_factor / max_centrality if max_centrality > 0 else 0.0
                        risk = d_factor * (0.5 + 0.5 * norm_centrality)

                        existing = best.get(current)
                        if existing is None or risk > existing.risk_contribution:
                            best[current] = DownstreamImpact(
                                file_path=current,
                                distance=dist,
                                via_files=list(path),
                                risk_contribution=risk,
                            )

                if dist >= max_depth:
                    continue

                for dep in self.file_graph.dependents(current):
                    if dep not in visited:
                        visited.add(dep)
                        queue.append((dep, dist + 1, path + [dep]))

        return sorted(best.values(), key=lambda imp: (-imp.risk_contribution, imp.file_path))

    def score_distance(self, distance: int) -> float:
        """Convert hop distance to risk: 1-hop=0.8, 2-hop=0.4, 3-hop=0.1."""
        return _DISTANCE_SCORES.get(distance, 0.0)

    def score_centrality(self, file_path: str) -> float:
        """Score based on how central the changed file is."""
        return float(self.file_graph.centrality(file_path))

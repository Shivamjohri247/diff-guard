from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from diff_guard.models import Change, DiffGuardConfig, IntendedScope, PhantomChange
from diff_guard.utils.file_graph import FileGraph

# ---------------------------------------------------------------------------
# Auto-ignore categories (Amendment 3b)
# ---------------------------------------------------------------------------

AUTO_IGNORE_CATEGORIES: dict[str, dict[str, list[str] | str]] = {
    "lockfiles": {
        "patterns": [
            "*.lock",
            "package-lock.json",
            "yarn.lock",
            "poetry.lock",
            "Pipfile.lock",
            "Gemfile.lock",
            "pnpm-lock.yaml",
        ],
        "reason": "Dependency lockfiles auto-update when packages change",
    },
    "generated": {
        "patterns": [
            "*.min.js",
            "*.min.css",
            "*.map",
            "*.d.ts",
            "dist/",
            "build/",
            "__pycache__/",
        ],
        "reason": "Auto-generated files change as a side effect of source changes",
    },
    "config_drift": {
        "patterns": [".env.example", "*.sample", "docker-compose.yml"],
        "reason": "Config files often need minor updates alongside feature changes",
        "severity": "info",
    },
    "migrations": {
        "patterns": ["migrations/", "alembic/versions/", "prisma/migrations/"],
        "reason": "Database migrations are expected side effects of model changes",
        "severity": "info",
    },
}

# ---------------------------------------------------------------------------
# Relevance-scoring weights
# ---------------------------------------------------------------------------

_WEIGHT_EXPLICIT: float = 0.40
_WEIGHT_PATH: float = 0.25
_WEIGHT_PROXIMITY: float = 0.15
_WEIGHT_IMPORT_CHAIN: float = 0.20

# Import-chain distance-to-score mapping
_HOP_SCORES: dict[int, float] = {0: 1.0, 1: 0.7, 2: 0.4}

# Dynamic-threshold multipliers (Amendment 2 / 3)
_CONFIDENCE_FACTOR_1: float = 0.5
_CONFIDENCE_MULTIPLIER_1: float = 1.5
_CONFIDENCE_FACTOR_2: float = 0.4
_CONFIDENCE_MULTIPLIER_2: float = 2.0


class PhantomChangeDetector:
    """Detects changes outside the intended scope with anti-false-positive measures."""

    def __init__(
        self,
        file_graph: FileGraph | None = None,
        config: DiffGuardConfig | None = None,
    ) -> None:
        self.file_graph = file_graph
        self.config = config or DiffGuardConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self, changes: list[Change], scope: IntendedScope
    ) -> list[PhantomChange]:
        """Main entry: flag out-of-scope changes with confidence scores.

        Only returns phantom changes whose relevance is below the (possibly
        dynamically adjusted) threshold.  Auto-ignored files are still
        returned but always at severity ``"info"``.
        """
        threshold = self._effective_threshold(scope)

        phantoms: list[PhantomChange] = []
        for change in changes:
            relevance = self.compute_relevance(change, scope)

            # Always include auto-ignored files as info-level
            auto_ignored, ignore_reason = self.is_auto_ignored(change.file_path)
            if auto_ignored:
                phantoms.append(
                    PhantomChange(
                        file_path=change.file_path,
                        reason=ignore_reason,
                        relevance_score=relevance,
                        change_summary=self._summarize(change),
                        severity="info",
                        confidence=self.compute_confidence(
                            change, scope, relevance
                        ),
                        added_lines=change.added_lines,
                        removed_lines=change.removed_lines,
                    )
                )
                continue

            # Skip changes that are clearly in scope
            if relevance >= threshold:
                continue

            # Skip legitimate downstream changes (Amendment 3a)
            if self.is_legitimate_downstream(change.file_path, scope):
                continue

            severity = self.classify_severity(change, relevance, scope)
            confidence = self.compute_confidence(change, scope, relevance)

            reason = self._build_reason(change, scope, relevance)

            phantoms.append(
                PhantomChange(
                    file_path=change.file_path,
                    reason=reason,
                    relevance_score=relevance,
                    change_summary=self._summarize(change),
                    severity=severity,
                    confidence=confidence,
                    added_lines=change.added_lines,
                    removed_lines=change.removed_lines,
                )
            )

        return phantoms

    # ------------------------------------------------------------------
    # Relevance scoring
    # ------------------------------------------------------------------

    def compute_relevance(
        self, change: Change, scope: IntendedScope
    ) -> float:
        """Compute 0.0-1.0 relevance score for a change against the scope.

        Weighted combination of:
        - Explicit match (0.40): 1.0 if file in scope.target_files
        - Path match (0.25): path-component overlap with scope keywords/concepts
        - Proximity (0.15): directory distance to nearest scope file
        - Import chain (0.20): graph distance
        """
        explicit = self._score_explicit(change.file_path, scope)
        path_match = self._score_path_match(change.file_path, scope)
        proximity = self._score_proximity(change.file_path, scope)
        import_chain = self._score_import_chain(change.file_path, scope)

        return (
            _WEIGHT_EXPLICIT * explicit
            + _WEIGHT_PATH * path_match
            + _WEIGHT_PROXIMITY * proximity
            + _WEIGHT_IMPORT_CHAIN * import_chain
        )

    # ------------------------------------------------------------------
    # Auto-ignore (Amendment 3b)
    # ------------------------------------------------------------------

    def is_auto_ignored(self, file_path: str) -> tuple[bool, str]:
        """Check if *file_path* matches any auto-ignore category.

        Returns ``(True, reason)`` if matched, ``(False, "")`` otherwise.
        """
        for _cat_name, cat_def in AUTO_IGNORE_CATEGORIES.items():
            patterns: list[str] = cat_def.get("patterns", [])  # type: ignore[assignment]
            for pattern in patterns:
                if self._matches_pattern(file_path, pattern):
                    reason: str = cat_def.get("reason", "Auto-ignored file")  # type: ignore[assignment]
                    return True, reason
        return False, ""

    # ------------------------------------------------------------------
    # Legitimate downstream (Amendment 3a)
    # ------------------------------------------------------------------

    def is_legitimate_downstream(
        self, file_path: str, scope: IntendedScope
    ) -> bool:
        """Check if *file_path* is within 2 hops of any in-scope file."""
        if self.file_graph is None:
            return False
        for target_file in scope.target_files:
            reachable = self.file_graph.files_within_hops(target_file, 2)
            # Normalize for comparison
            normalized_file = PurePosixPath(file_path).as_posix()
            for reachable_file in reachable:
                if reachable_file == normalized_file:
                    return True
        return False

    # ------------------------------------------------------------------
    # Severity classification
    # ------------------------------------------------------------------

    def classify_severity(
        self, change: Change, relevance: float, scope: IntendedScope
    ) -> str:
        """Classify as ``'info'``, ``'warning'``, or ``'critical'``."""
        threshold = self._effective_threshold(scope)
        lines_changed = change.added_lines + change.removed_lines
        centrality = self._get_centrality(change.file_path)

        # Auto-ignored file or very small change -> info
        auto_ignored, _ = self.is_auto_ignored(change.file_path)
        if auto_ignored or lines_changed <= 2:
            return "info"

        # Critical: below threshold, significant changes, high centrality
        if relevance < threshold and lines_changed > 5 and centrality > 5:
            return "critical"

        # Warning: below threshold OR low relevance with moderate centrality
        if relevance < threshold or (relevance < 0.4 and centrality > 3):
            return "warning"

        return "info"

    # ------------------------------------------------------------------
    # Detection confidence
    # ------------------------------------------------------------------

    def compute_confidence(
        self, change: Change, scope: IntendedScope, relevance: float
    ) -> float:
        """Compute detection confidence (how sure we are this is truly unintended).

        - High (>= 0.9): no import-chain connection AND no path overlap AND
          significant changes
        - Medium (0.5-0.9): some path overlap or 1-hop connection but not in
          scope
        - Low (< 0.5): auto-ignored file OR very small change OR 2-hop
          connection exists
        """
        path_overlap = self._score_path_match(change.file_path, scope) > 0.0
        chain_score = self._score_import_chain(change.file_path, scope)
        lines_changed = change.added_lines + change.removed_lines

        auto_ignored, _ = self.is_auto_ignored(change.file_path)
        has_2hop = self._has_n_hop_connection(change.file_path, scope, 2)

        # Low confidence
        if auto_ignored or lines_changed <= 2 or has_2hop:
            return min(0.4, max(0.1, relevance))

        # High confidence: truly disconnected, significant change
        if (
            chain_score == 0.0
            and not path_overlap
            and lines_changed > 3
        ):
            return 0.9 + min(0.1, (1.0 - relevance) * 0.2)

        # Medium confidence: some overlap but not fully in scope
        if path_overlap or chain_score > 0.0:
            return 0.5 + min(0.4, chain_score * 0.3)

        return 0.6

    # ------------------------------------------------------------------
    # Private helpers — scoring components
    # ------------------------------------------------------------------

    def _score_explicit(self, file_path: str, scope: IntendedScope) -> float:
        """1.0 if *file_path* is in scope.target_files, else 0.0."""
        normalized = PurePosixPath(file_path).as_posix()
        for target in scope.target_files:
            if PurePosixPath(target).as_posix() == normalized:
                return 1.0
        return 0.0

    def _score_path_match(self, file_path: str, scope: IntendedScope) -> float:
        """Path-component overlap with scope keywords / concepts.

        Returns the fraction of path components that match any scope keyword
        or concept, capped at 1.0.
        """
        parts = PurePosixPath(file_path).parts
        stems = {PurePosixPath(p).stem.lower() for p in parts}

        keywords = {c.lower() for c in scope.target_concepts}
        # Also use target file stems and function names as keywords
        for tf in scope.target_files:
            keywords.add(PurePosixPath(tf).stem.lower())
        for func in scope.target_functions:
            keywords.add(func.lower())

        if not keywords or not stems:
            return 0.0

        overlap = len(stems & keywords)
        total = len(stems)
        if total == 0:
            return 0.0
        return min(1.0, overlap / total)

    def _score_proximity(
        self, file_path: str, scope: IntendedScope
    ) -> float:
        """Directory distance to nearest scope file.

        Same directory = 1.0, parent/child = 0.7, same tree = 0.3, else 0.0.
        """
        if not scope.target_files:
            return 0.0

        file_parts = PurePosixPath(file_path).parts
        best_score = 0.0

        for target in scope.target_files:
            target_parts = PurePosixPath(target).parts

            # Count common prefix directories (excluding filename)
            file_dirs = file_parts[:-1]
            target_dirs = target_parts[:-1]

            common = 0
            for fd, td in zip(file_dirs, target_dirs):
                if fd == td:
                    common += 1
                else:
                    break

            if common == 0:
                score = 0.0
            else:
                max_depth = max(len(file_dirs), len(target_dirs))
                if max_depth == 0:
                    score = 1.0
                else:
                    score = min(1.0, common / max_depth)

            if score > best_score:
                best_score = score

        return best_score

    def _score_import_chain(
        self, file_path: str, scope: IntendedScope
    ) -> float:
        """Graph distance score: 0 hops=1.0, 1 hop=0.7, 2 hops=0.4, 3+=0.0."""
        if self.file_graph is None or not scope.target_files:
            return 0.0

        best_score = 0.0
        for target in scope.target_files:
            dist = self.file_graph.distance(target, file_path)
            if dist == -1:
                continue
            score = _HOP_SCORES.get(dist, 0.0)
            if score > best_score:
                best_score = score

        return best_score

    # ------------------------------------------------------------------
    # Private helpers — thresholds
    # ------------------------------------------------------------------

    def _effective_threshold(self, scope: IntendedScope) -> float:
        """Return the phantom-relevance threshold, dynamically adjusted.

        When scope confidence < 0.5: threshold *= 1.5
        When scope confidence < 0.4: threshold *= 2.0
        """
        base = self.config.thresholds.phantom_relevance
        if scope.confidence < _CONFIDENCE_FACTOR_2:
            return base * _CONFIDENCE_MULTIPLIER_2
        if scope.confidence < _CONFIDENCE_FACTOR_1:
            return base * _CONFIDENCE_MULTIPLIER_1
        return base

    # ------------------------------------------------------------------
    # Private helpers — misc
    # ------------------------------------------------------------------

    def _get_centrality(self, file_path: str) -> int:
        """Return centrality for *file_path* (0 if no graph available)."""
        if self.file_graph is None:
            return 0
        return self.file_graph.centrality(file_path)

    def _has_n_hop_connection(
        self, file_path: str, scope: IntendedScope, max_hops: int
    ) -> bool:
        """Check if *file_path* is within *max_hops* of any in-scope file."""
        if self.file_graph is None:
            return False
        normalized = PurePosixPath(file_path).as_posix()
        for target in scope.target_files:
            reachable = self.file_graph.files_within_hops(target, max_hops)
            for r in reachable:
                if r == normalized:
                    return True
        return False

    def _matches_pattern(self, file_path: str, pattern: str) -> bool:
        """Match *file_path* against a glob-style or path-prefix pattern."""
        normalized = PurePosixPath(file_path).as_posix()
        # Directory-prefix pattern (ends with /)
        if pattern.endswith("/"):
            return normalized.startswith(pattern) or f"/{pattern}" in f"/{normalized}"
        # Glob / exact match
        return fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
            PurePosixPath(file_path).name, pattern
        )

    def _summarize(self, change: Change) -> str:
        """Build a short human-readable summary of a change."""
        parts: list[str] = []
        if change.is_new_file:
            parts.append("New file")
        elif change.is_deleted:
            parts.append("Deleted file")
        else:
            parts.append("Modified")
        parts.append(change.file_path)
        if change.functions_modified:
            parts.append(f"(functions: {', '.join(change.functions_modified)})")
        parts.append(
            f"[+{change.added_lines}/-{change.removed_lines}]"
        )
        return " ".join(parts)

    def _build_reason(
        self, change: Change, scope: IntendedScope, relevance: float
    ) -> str:
        """Build a human-readable reason for why a change was flagged."""
        reasons: list[str] = []
        if self._score_explicit(change.file_path, scope) == 0.0:
            reasons.append("not in scope target files")
        if self._score_path_match(change.file_path, scope) == 0.0:
            reasons.append("no path overlap with scope")
        else:
            reasons.append("partial path overlap with scope")
        if self._score_import_chain(change.file_path, scope) == 0.0:
            reasons.append("no import-chain connection to scope")
        else:
            reasons.append("weak import-chain connection")
        reasons.append(f"relevance={relevance:.2f}")
        return "; ".join(reasons)

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChangeType(Enum):
    """Type of change detected in a file."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass
class Hunk:
    """A contiguous block of lines changed in a diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    function_header: str | None = None


@dataclass
class Change:
    """Represents a single file change from a diff."""

    file_path: str
    change_type: ChangeType
    hunks: list[Hunk]
    added_lines: int
    removed_lines: int
    functions_modified: list[str] = field(default_factory=list)
    imports_modified: list[str] = field(default_factory=list)
    language: str = "unknown"
    is_new_file: bool = False
    is_deleted: bool = False
    old_path: str | None = None


@dataclass
class IntendedScope:
    """The developer's intended scope of changes."""

    description: str
    target_files: set[str] = field(default_factory=set)
    target_functions: set[str] = field(default_factory=set)
    target_concepts: set[str] = field(default_factory=set)
    confidence: float = 0.0
    source: str = "inferred"


@dataclass
class PhantomChange:
    """A change that falls outside the intended scope."""

    file_path: str
    reason: str
    relevance_score: float
    change_summary: str
    severity: str  # "info" | "warning" | "critical"
    confidence: float
    added_lines: int = 0
    removed_lines: int = 0


@dataclass
class DownstreamImpact:
    """A file affected indirectly through the import/dependency chain."""

    file_path: str
    distance: int
    via_files: list[str]
    risk_contribution: float


@dataclass
class TestSuggestion:
    """A test file matched to a changed source file."""

    test_file: str
    changed_file: str
    match_reason: str
    confidence: float


@dataclass
class BlastRadiusReport:
    """Complete blast radius analysis report."""

    changed_files: list[Change]
    intended_scope: IntendedScope
    phantom_changes: list[PhantomChange]
    downstream_impacts: list[DownstreamImpact]
    risk_score: float
    risk_level: str  # "safe" | "review" | "danger"
    suggested_tests: list[TestSuggestion]
    commit_message_quality: CommitMessageQuality | None = None


@dataclass
class CommitMessageQuality:
    """Quality assessment of a commit message."""

    message: str
    score: float  # 0.0 (terrible) to 1.0 (good)
    issues: list[str] = field(default_factory=list)
    is_vague: bool = False
    suggested_improvement: str | None = None


@dataclass
class Thresholds:
    """Numeric thresholds used for risk classification."""

    phantom_relevance: float = 0.3
    risk_safe: float = 0.3
    risk_danger: float = 0.6


@dataclass
class TestConfig:
    """Configuration for test file discovery and command generation."""

    directories: list[str] = field(
        default_factory=lambda: ["tests/", "test/", "__tests__/", "spec/"]
    )
    patterns: list[str] = field(
        default_factory=lambda: ["test_*.py", "*_test.py", "*.test.ts", "*.test.js", "*.spec.js"]
    )
    command: str = "pytest {files} -v"


@dataclass
class ScopeConfig:
    """Configuration for scope inference from prompt files."""

    prompt_files: list[str] = field(
        default_factory=lambda: [".diff-guard-prompt", ".claude-prompt", ".cursor-prompt"]
    )
    areas: dict[str, dict[str, list[str]]] = field(default_factory=dict)


@dataclass
class HookConfig:
    """Configuration for running as a git pre-commit hook."""

    fail_on: str = "danger"
    auto_test: bool = False
    show_report: bool = True
    mode: str = "full"  # "test-only" | "full" | "check-only"


@dataclass
class DiffGuardConfig:
    """Top-level configuration for diff-guard."""

    thresholds: Thresholds = field(default_factory=Thresholds)
    ignore: list[str] = field(default_factory=list)
    tests: TestConfig = field(default_factory=TestConfig)
    scope: ScopeConfig = field(default_factory=ScopeConfig)
    hook: HookConfig = field(default_factory=HookConfig)
    languages: dict[str, dict[str, str]] = field(default_factory=dict)

"""Commit message quality checker for AI-generated commits.

Heuristic-based analysis that flags vague, uninformative commit messages
commonly produced by AI coding agents.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from diff_guard.models import Change, CommitMessageQuality

# Messages that are too vague to be useful.
_VAGUE_WORDS: frozenset[str] = frozenset(
    {
        "fix",
        "update",
        "wip",
        "changes",
        "stuff",
        "misc",
        "cleanup",
        "tidy",
        "things",
        "done",
        "asdf",
        "temp",
        "test",
        "minor",
        "tweak",
        "refactor",
        "adjust",
        "change",
        "modify",
    }
)

# Conventional commit pattern: type(scope)?: description
_CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\([^)]+\))?"
    r":\s+.+",
    re.IGNORECASE,
)

# Minimum length for a reasonable commit message
_MIN_LENGTH = 10


def check_commit_message(
    message: str,
    changes: list[Change],
) -> CommitMessageQuality:
    """Evaluate commit message quality against actual changes.

    Returns a :class:`CommitMessageQuality` with score, issues, and
    an optional suggested improvement.
    """
    if not message or not message.strip():
        return CommitMessageQuality(
            message=message,
            score=0.0,
            issues=["Empty commit message"],
            is_vague=True,
            suggested_improvement=_suggest_from_changes(changes),
        )

    stripped = message.strip()
    first_line = stripped.split("\n", 1)[0].strip()
    lower = first_line.lower()

    score = 1.0
    issues: list[str] = []

    # 1. Vague word detection
    is_vague = lower in _VAGUE_WORDS
    if is_vague:
        score -= 0.3
        issues.append(f"Vague commit message: '{first_line}'")

    # 2. Length check
    if len(first_line) < _MIN_LENGTH:
        score -= 0.2
        issues.append(f"Commit message too short ({len(first_line)} chars, minimum {_MIN_LENGTH})")

    # 3. Scope correlation
    if not _scope_correlates(lower, changes):
        score -= 0.2
        issues.append("Message does not reference changed files or modules")

    # 4. Conventional commit format
    if _CONVENTIONAL_RE.match(first_line):
        # Small bonus but cap at 1.0
        score = min(1.0, score + 0.1)
    else:
        score -= 0.1
        issues.append("Does not follow conventional commit format (type(scope): description)")

    score = max(0.0, min(1.0, score))

    # Suggest improvement if score is low
    suggested = None
    if score < 0.5 and changes:
        suggested = _suggest_from_changes(changes)

    return CommitMessageQuality(
        message=message,
        score=round(score, 2),
        issues=issues,
        is_vague=is_vague,
        suggested_improvement=suggested,
    )


def _scope_correlates(message_lower: str, changes: list[Change]) -> bool:
    """Check if the message mentions any changed file or module."""
    if not changes:
        return True

    # Extract keywords from message
    words = set(re.findall(r"[a-z_]+", message_lower))

    for change in changes:
        # Check file stem
        stem = PurePosixPath(change.file_path).stem.lower()
        if stem in words:
            return True

        # Check path components
        parts = PurePosixPath(change.file_path).parts
        for part in parts:
            part_lower = part.lower().rstrip(".py").rstrip(".js").rstrip(".ts")
            if len(part_lower) > 2 and part_lower in words:
                return True

        # Check modified functions
        for func in change.functions_modified:
            func_lower = func.lower()
            if func_lower in words:
                return True

    return False


def _suggest_from_changes(changes: list[Change]) -> str | None:
    """Generate a suggested commit message from the actual changes."""
    if not changes:
        return None

    # Determine type
    change_types = {c.change_type.value for c in changes}
    if "added" in change_types and len(change_types) == 1:
        prefix = "feat"
    elif "deleted" in change_types and len(change_types) == 1:
        prefix = "refactor"
    else:
        prefix = "fix"

    # Determine scope from common path prefix
    files = [c.file_path for c in changes]
    if len(files) == 1:
        scope = PurePosixPath(files[0]).stem
    else:
        # Find common parent directory
        parts_list = [PurePosixPath(f).parts for f in files]
        common_parts: list[str] = []
        for parts in zip(*parts_list, strict=True):
            if len(set(parts)) == 1:
                common_parts.append(parts[0])
            else:
                break
        scope = common_parts[-1] if common_parts else ""

    # Build description
    if len(files) == 1:
        desc = f"update {PurePosixPath(files[0]).stem}"
    elif len(files) <= 3:
        stems = [PurePosixPath(f).stem for f in files]
        desc = f"update {', '.join(stems)}"
    else:
        desc = f"update {len(files)} files in {scope or 'project'}"

    if scope:
        return f"{prefix}({scope}): {desc}"
    return f"{prefix}: {desc}"

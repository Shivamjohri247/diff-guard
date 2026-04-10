"""Parser for ``.diff-guard-ignore`` files.

Format follows ``.gitignore`` conventions:
- One pattern per line
- ``#`` starts a comment
- Blank lines are ignored
- ``!`` prefix negates a pattern (un-ignores a previously matched file)
- Trailing whitespace is trimmed
"""

from __future__ import annotations

from pathlib import Path


def load_ignore_file(repo_root: Path) -> list[str]:
    """Load ignore patterns from a ``.diff-guard-ignore`` file.

    Returns a list of patterns.  Negation patterns (starting with ``!``)
    are included in the list as-is so callers can apply them.

    Returns an empty list if the file does not exist.
    """
    ignore_path = repo_root.resolve() / ".diff-guard-ignore"
    if not ignore_path.is_file():
        return []

    patterns: list[str] = []
    try:
        text = ignore_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    for line in text.splitlines():
        stripped = line.strip()
        # Skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)

    return patterns

from __future__ import annotations

import re
from pathlib import Path

from diff_guard.models import Change, ChangeType, Hunk
from diff_guard.utils.git import (
    get_diff_from_ref,
    get_last_commit_diff,
    get_staged_diff,
)

# Language detection by file extension
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}

# Import patterns for detecting modified imports
IMPORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\+\s*(?:import\s+\S+|from\s+\S+\s+import\s+)"),
    re.compile(r"^\-\s*(?:import\s+\S+|from\s+\S+\s+import\s+)"),
    re.compile(r"^\+\s*(?:import\s+.*from\s+['\"].*['\"]|const\s+\w+\s*=\s*require\s*\()"),
    re.compile(r"^\-\s*(?:import\s+.*from\s+['\"].*['\"]|const\s+\w+\s*=\s*require\s*\()"),
    re.compile(r"^\+\s*(?:export\s+)"),
    re.compile(r"^\-\s*(?:export\s+)"),
]


def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    suffix = Path(file_path).suffix.lower()
    return EXTENSION_MAP.get(suffix, "unknown")


def parse_staged_diff(repo_root: Path | None = None) -> list[Change]:
    """Run git diff --staged and parse into Change objects."""
    diff_text = get_staged_diff(repo_root)
    return parse_unified_diff(diff_text)


def parse_diff_from_ref(ref: str, repo_root: Path | None = None) -> list[Change]:
    """Parse diff between HEAD and a git ref."""
    diff_text = get_diff_from_ref(ref, repo_root)
    return parse_unified_diff(diff_text)


def parse_last_commit(repo_root: Path | None = None) -> list[Change]:
    """Parse diff from the last commit."""
    diff_text = get_last_commit_diff(repo_root)
    return parse_unified_diff(diff_text)


def parse_unified_diff(diff_text: str) -> list[Change]:
    """Parse unified diff text into a list of Change objects."""
    if not diff_text.strip():
        return []

    changes: list[Change] = []
    # Split into per-file sections
    file_sections = re.split(r"^diff --git ", diff_text, flags=re.MULTILINE)

    for section in file_sections:
        if not section.strip():
            continue
        change = _parse_file_section(section)
        if change is not None:
            changes.append(change)

    return changes


def _parse_file_section(section: str) -> Change | None:
    """Parse a single file's diff section into a Change object."""
    lines = section.split("\n")

    # Extract file paths from header lines
    file_path, change_type = _extract_file_paths(lines)
    if file_path is None:
        return None

    # Detect special modes
    is_new_file = any(line.startswith("new file mode") for line in lines[:10])
    is_deleted = any(line.startswith("deleted file mode") for line in lines[:10])

    # Detect rename
    old_path: str | None = None
    if change_type == ChangeType.RENAMED:
        for line in lines:
            if line.startswith("rename from "):
                old_path = line[len("rename from "):]
                break

    # Parse hunks
    hunks = _parse_hunks(section)

    # Count added/removed lines
    added_lines = 0
    removed_lines = 0
    added_content: list[str] = []
    removed_content: list[str] = []

    for hunk in hunks:
        for hline in hunk.content.split("\n"):
            if hline.startswith("+") and not hline.startswith("+++"):
                added_lines += 1
                added_content.append(hline[1:])
            elif hline.startswith("-") and not hline.startswith("---"):
                removed_lines += 1
                removed_content.append(hline[1:])

    # Extract modified functions from hunk headers
    functions_modified: list[str] = []
    for hunk in hunks:
        if hunk.function_header:
            # Git puts function/class names in the @@ header
            func_name = _extract_function_from_header(hunk.function_header)
            if func_name and func_name not in functions_modified:
                functions_modified.append(func_name)

    # Detect modified imports
    imports_modified = _detect_modified_imports(added_content, removed_content)

    language = detect_language(file_path)

    return Change(
        file_path=file_path,
        change_type=change_type,
        hunks=hunks,
        added_lines=added_lines,
        removed_lines=removed_lines,
        functions_modified=functions_modified,
        imports_modified=imports_modified,
        language=language,
        is_new_file=is_new_file,
        is_deleted=is_deleted,
        old_path=old_path,
    )


def _extract_file_paths(lines: list[str]) -> tuple[str | None, ChangeType]:
    """Extract file path and change type from diff header lines."""
    old_path: str | None = None
    new_path: str | None = None

    for line in lines[:10]:
        if line.startswith("--- "):
            p = line[4:].strip()
            if p != "/dev/null":
                # Strip a/ prefix
                old_path = p[2:] if p.startswith("a/") else p
        elif line.startswith("+++ "):
            p = line[4:].strip()
            if p != "/dev/null":
                # Strip b/ prefix
                new_path = p[2:] if p.startswith("b/") else p

    if new_path is None:
        if old_path is not None:
            return old_path, ChangeType.DELETED
        return None, ChangeType.MODIFIED

    # Determine change type
    if old_path is None:
        return new_path, ChangeType.ADDED

    # Check for rename
    for line in lines[:10]:
        if line.startswith("rename from "):
            return new_path, ChangeType.RENAMED

    if old_path is not None and old_path != new_path:
        return new_path, ChangeType.RENAMED

    return new_path, ChangeType.MODIFIED


def _parse_hunks(section: str) -> list[Hunk]:
    """Parse @@ -old,count +new,count @@ hunks from diff body."""
    hunks: list[Hunk] = []
    hunk_pattern = re.compile(
        r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$",
        re.MULTILINE,
    )

    matches = list(hunk_pattern.finditer(section))
    for i, match in enumerate(matches):
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) is not None else 1
        function_header = match.group(5).strip() if match.group(5) else None

        # Extract content: from this hunk header to the next (or end)
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        content = section[content_start:content_end]

        hunks.append(
            Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                content=content,
                function_header=function_header if function_header else None,
            )
        )

    return hunks


def _extract_function_from_header(header: str) -> str | None:
    """Extract function/class name from the @@ hunk header annotation."""
    # Git annotates with things like "@@ -10,5 +10,7 @@ def my_function"
    # or "@@ -1,3 +1,4 @@ class MyClass"
    header = header.strip()
    if not header:
        return None

    # Take the first word after the @@ marker (skip leading whitespace)
    parts = header.split()
    if not parts:
        return None

    # Skip common prefixes like "def", "class", "fn", "func", "function"
    token = parts[0]
    if token in ("def", "class", "fn", "func", "function", "public", "private", "static"):
        if len(parts) > 1:
            # Take the next token, strip parens
            name = parts[1].split("(")[0].split(":")[0].strip()
            return name if name else None
        return None

    # Otherwise take the first token, strip parens
    name = token.split("(")[0].split(":")[0].strip()
    return name if name else None


def _detect_modified_imports(added_lines: list[str], removed_lines: list[str]) -> list[str]:
    """Detect import statements that were added or removed."""
    imports: list[str] = []
    seen: set[str] = set()

    for line in added_lines + removed_lines:
        stripped = line.strip()
        for pattern in IMPORT_PATTERNS:
            # We already know the line starts with import/from/const/export
            # because we collected only +/- lines
            pass

        # Python imports
        py_import = re.match(r"^(?:import\s+(\S+)|from\s+(\S+)\s+import\s+(.+))", stripped)
        if py_import:
            if py_import.group(1):
                imp = py_import.group(1)
            else:
                imp = f"{py_import.group(2)}.{py_import.group(3).strip()}"
            if imp not in seen:
                imports.append(imp)
                seen.add(imp)
            continue

        # JS/TS imports
        js_import = re.match(
            r"^(?:import\s+.*from\s+['\"](.+?)['\"]|const\s+\w+\s*=\s*require\s*\(\s*['\"](.+?)['\"]\s*\))",
            stripped,
        )
        if js_import:
            imp = js_import.group(1) or js_import.group(2)
            if imp and imp not in seen:
                imports.append(imp)
                seen.add(imp)
            continue

        # Go imports
        go_import = re.match(r'^import\s+(?:"(.+?)"|\w+\s+"(.+?)")', stripped)
        if go_import:
            imp = go_import.group(1) or go_import.group(2)
            if imp and imp not in seen:
                imports.append(imp)
                seen.add(imp)

    return imports

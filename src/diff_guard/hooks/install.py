from __future__ import annotations

import stat
from pathlib import Path

from diff_guard.utils.git import get_repo_root

HOOK_MARKER_START = "# >>> diff-guard >>>"
HOOK_MARKER_END = "# <<< diff-guard <<<"


def generate_hook_script(fail_on: str = "danger", mode: str = "full") -> str:
    """Generate the diff-guard block for the pre-commit hook.

    The block uses marker comments so that it can be identified, replaced,
    or removed later without disturbing other hook content.
    """
    if mode == "test-only":
        diff_guard_cmd = "diff-guard test --staged --command-only"
    else:
        diff_guard_cmd = f"diff-guard check --staged --fail-on {fail_on}"

    lines = [
        HOOK_MARKER_START,
        f"{diff_guard_cmd}",
        HOOK_MARKER_END,
    ]
    return "\n".join(lines) + "\n"


def _resolve_hooks_dir(repo_root: Path | None = None) -> Path:
    """Return the ``.git/hooks`` directory, creating it if necessary."""
    root = repo_root if repo_root is not None else get_repo_root()
    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir


def install_hook(
    repo_root: Path | None = None,
    fail_on: str = "danger",
    mode: str = "full",
) -> Path:
    """Install diff-guard as a pre-commit hook.

    If ``.git/hooks/pre-commit`` already exists:

    - If it already contains diff-guard markers, the diff-guard block is
      **replaced** in-place.
    - Otherwise the diff-guard block is **appended** with a blank-line
      separator.

    The hook file is made executable (``chmod 0o755``).

    Returns the path to the hook file.
    """
    hooks_dir = _resolve_hooks_dir(repo_root)
    hook_path = hooks_dir / "pre-commit"
    new_block = generate_hook_script(fail_on=fail_on, mode=mode)

    if hook_path.exists():
        existing = hook_path.read_text()
        if HOOK_MARKER_START in existing:
            # Replace the existing diff-guard block in-place.
            before = existing[: existing.index(HOOK_MARKER_START)]
            after = existing[existing.index(HOOK_MARKER_END) + len(HOOK_MARKER_END) :]
            content = before + new_block + after
        else:
            # Append with a blank separator line.
            content = existing.rstrip("\n") + "\n\n" + new_block
    else:
        # New file: add shebang header.
        content = "#!/bin/sh\n" + new_block

    hook_path.write_text(content)
    hook_path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return hook_path


def uninstall_hook(repo_root: Path | None = None) -> bool:
    """Remove the diff-guard block from the pre-commit hook.

    If the file becomes empty (or contains only whitespace / comments)
    after removal, the file is deleted.

    If other hook content is present, it is left intact.

    Returns ``True`` if the uninstall was successful, ``False`` if no
    diff-guard block was found.
    """
    hooks_dir = _resolve_hooks_dir(repo_root)
    hook_path = hooks_dir / "pre-commit"

    if not hook_path.exists():
        return False

    existing = hook_path.read_text()

    if HOOK_MARKER_START not in existing:
        return False

    before = existing[: existing.index(HOOK_MARKER_START)]
    after = existing[existing.index(HOOK_MARKER_END) + len(HOOK_MARKER_END) :]

    remaining = before + after

    # Strip leading/trailing blank lines from the remaining content.
    stripped = remaining.strip()
    if not stripped or all(
        line.strip() == "" or line.strip().startswith("#")
        for line in stripped.splitlines()
        if line.strip()
    ):
        # File is empty or only contains comments/blank lines -- remove it.
        hook_path.unlink()
        return True

    hook_path.write_text(remaining)
    return True


def is_hook_installed(repo_root: Path | None = None) -> bool:
    """Check whether diff-guard hook is installed in ``.git/hooks/pre-commit``."""
    hooks_dir = _resolve_hooks_dir(repo_root)
    hook_path = hooks_dir / "pre-commit"

    if not hook_path.exists():
        return False

    content = hook_path.read_text()
    return HOOK_MARKER_START in content

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(args: list[str], repo_root: Path | None = None) -> str:
    """Run a git command and return stdout. Raises on non-zero exit."""
    cmd = ["git"]
    if repo_root is not None:
        cmd.extend(["-C", str(repo_root)])
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def get_repo_root() -> Path:
    """Return the root directory of the current git repository."""
    output = run_git(["rev-parse", "--show-toplevel"])
    return Path(output.strip())


def get_staged_diff(repo_root: Path | None = None) -> str:
    """Return the full staged diff text."""
    return run_git(["diff", "--staged", "--unified=3"], repo_root)


def get_diff_from_ref(ref: str, repo_root: Path | None = None) -> str:
    """Return diff between current state and a git ref."""
    return run_git(["diff", ref, "--unified=3"], repo_root)


def get_last_commit_diff(repo_root: Path | None = None) -> str:
    """Return diff from the last commit."""
    return run_git(["diff", "HEAD~1", "HEAD", "--unified=3"], repo_root)


def get_commit_message(repo_root: Path | None = None) -> str:
    """Return the current commit message (for scope extraction)."""
    try:
        return run_git(["log", "--format=%B", "-1"], repo_root).strip()
    except subprocess.CalledProcessError:
        return ""


def get_staged_commit_message(repo_root: Path | None = None) -> str:
    """Return the staged commit message from .git/COMMIT_EDITMSG."""
    try:
        root = repo_root or get_repo_root()
        msg_file = root / ".git" / "COMMIT_EDITMSG"
        if msg_file.exists():
            return msg_file.read_text().strip()
    except (OSError, ValueError):
        pass
    return ""


def get_file_at_head(path: str, repo_root: Path | None = None) -> str | None:
    """Return file contents at HEAD, or None if the file didn't exist."""
    try:
        return run_git(["show", f"HEAD:{path}"], repo_root)
    except subprocess.CalledProcessError:
        return None

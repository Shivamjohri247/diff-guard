from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_as_hook(repo_root: Path | None = None, mode: str = "full", fail_on: str = "danger") -> int:
    """Entry point when called from the git hook script.

    Runs the appropriate diff-guard command based on *mode*:

    - "test-only": runs ``diff-guard test --staged --command-only``
    - "check-only": runs ``diff-guard check --staged --fail-on <fail_on>``
    - "full": runs ``diff-guard check --staged --fail-on <fail_on>``

    The command is executed as a subprocess so that the hook process
    inherits diff-guard's exit code directly.
    """
    if mode == "test-only":
        cmd = [sys.executable, "-m", "diff_guard", "test", "--staged", "--command-only"]
    else:
        # Both "check-only" and "full" run the check command.
        cmd = [sys.executable, "-m", "diff_guard", "check", "--staged", "--fail-on", fail_on]

    result = subprocess.run(cmd, cwd=str(repo_root) if repo_root is not None else None)
    return result.returncode

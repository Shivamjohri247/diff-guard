from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from diff_guard.utils.git import (
    get_commit_message,
    get_diff_from_ref,
    get_file_at_head,
    get_last_commit_diff,
    get_repo_root,
    get_staged_commit_message,
    get_staged_diff,
    run_git,
)


class TestRunGit:
    def test_basic_command(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="output\n")
            result = run_git(["status"])
            mock_run.assert_called_once()
            assert result == "output\n"

    def test_with_repo_root(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok")
            run_git(["status"], repo_root=Path("/tmp/repo"))
            cmd = mock_run.call_args[0][0]
            assert "-C" in cmd
            assert "/tmp/repo" in cmd

    def test_raises_on_failure(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")
            try:
                run_git(["status"])
                raise AssertionError("Should have raised")
            except subprocess.CalledProcessError:
                pass


class TestGetRepoRoot:
    def test_returns_path(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="/home/user/project\n")
            result = get_repo_root()
            assert result == Path("/home/user/project")


class TestGetStagedDiff:
    def test_calls_diff_staged(self) -> None:
        with patch("diff_guard.utils.git.run_git", return_value="diff output") as mock:
            result = get_staged_diff(Path("/repo"))
            mock.assert_called_once_with(["diff", "--staged", "--unified=3"], Path("/repo"))
            assert result == "diff output"


class TestGetDiffFromRef:
    def test_calls_diff_with_ref(self) -> None:
        with patch("diff_guard.utils.git.run_git", return_value="diff") as mock:
            get_diff_from_ref("HEAD~3", Path("/repo"))
            mock.assert_called_once_with(["diff", "HEAD~3", "--unified=3"], Path("/repo"))


class TestGetLastCommitDiff:
    def test_calls_diff_head(self) -> None:
        with patch("diff_guard.utils.git.run_git", return_value="diff") as mock:
            get_last_commit_diff(Path("/repo"))
            mock.assert_called_once_with(["diff", "HEAD~1", "HEAD", "--unified=3"], Path("/repo"))


class TestGetCommitMessage:
    def test_returns_message(self) -> None:
        with patch("diff_guard.utils.git.run_git", return_value="feat: add login\n"):
            result = get_commit_message(Path("/repo"))
            assert result == "feat: add login"

    def test_returns_empty_on_failure(self) -> None:
        with patch(
            "diff_guard.utils.git.run_git", side_effect=subprocess.CalledProcessError(1, "git")
        ):
            result = get_commit_message(Path("/repo"))
            assert result == ""


class TestGetStagedCommitMessage:
    def test_reads_commit_editmsg(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "COMMIT_EDITMSG").write_text("fix: update auth\n")
        result = get_staged_commit_message(tmp_path)
        assert result == "fix: update auth"

    def test_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        result = get_staged_commit_message(tmp_path)
        assert result == ""


class TestGetFileAtHead:
    def test_returns_file_contents(self) -> None:
        with patch("diff_guard.utils.git.run_git", return_value="file content"):
            result = get_file_at_head("src/app.py", Path("/repo"))
            assert result == "file content"

    def test_returns_none_on_failure(self) -> None:
        with patch(
            "diff_guard.utils.git.run_git", side_effect=subprocess.CalledProcessError(1, "git")
        ):
            result = get_file_at_head("src/app.py", Path("/repo"))
            assert result is None

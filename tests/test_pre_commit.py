from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from diff_guard.hooks.pre_commit import run_as_hook


class TestRunAsHook:
    def test_test_only_mode(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = run_as_hook(Path("/repo"), mode="test-only")
            cmd = mock_run.call_args[0][0]
            assert "test" in cmd
            assert "--command-only" in cmd
            assert result == 0

    def test_check_only_mode(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = run_as_hook(Path("/repo"), mode="check-only", fail_on="review")
            cmd = mock_run.call_args[0][0]
            assert "check" in cmd
            assert "--fail-on" in cmd
            assert "review" in cmd
            assert result == 0

    def test_full_mode(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = run_as_hook(Path("/repo"), mode="full", fail_on="danger")
            cmd = mock_run.call_args[0][0]
            assert "check" in cmd
            assert "danger" in cmd
            assert result == 0

    def test_returns_nonzero_on_failure(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = run_as_hook(Path("/repo"), mode="full")
            assert result == 1

    def test_sets_cwd_to_repo_root(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_as_hook(Path("/repo"), mode="full")
            assert mock_run.call_args[1]["cwd"] == "/repo"

    def test_no_cwd_when_repo_root_is_none(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_as_hook(None, mode="full")
            assert mock_run.call_args[1]["cwd"] is None

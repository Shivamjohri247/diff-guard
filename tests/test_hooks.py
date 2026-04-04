from __future__ import annotations

import stat
from pathlib import Path

from diff_guard.hooks.install import (
    HOOK_MARKER_END,
    HOOK_MARKER_START,
    generate_hook_script,
    install_hook,
    is_hook_installed,
    uninstall_hook,
)


def _make_git_hooks_dir(tmp_path: Path) -> Path:
    """Create a fake .git/hooks directory under *tmp_path* and return it."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir


# ---------------------------------------------------------------------------
# generate_hook_script
# ---------------------------------------------------------------------------


class TestGenerateHookScript:
    def test_default_mode_generates_check_command(self) -> None:
        script = generate_hook_script()
        assert "#!/bin/sh" in script
        assert HOOK_MARKER_START in script
        assert HOOK_MARKER_END in script
        assert "diff-guard check --staged --fail-on danger" in script

    def test_test_only_mode(self) -> None:
        script = generate_hook_script(mode="test-only")
        assert "diff-guard test --staged --command-only" in script

    def test_custom_fail_on(self) -> None:
        script = generate_hook_script(fail_on="review", mode="full")
        assert "--fail-on review" in script

    def test_check_only_mode(self) -> None:
        script = generate_hook_script(fail_on="danger", mode="check-only")
        assert "diff-guard check --staged --fail-on danger" in script


# ---------------------------------------------------------------------------
# install_hook
# ---------------------------------------------------------------------------


class TestInstallHook:
    def test_install_hook_creates_file(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        hook_path = install_hook(repo_root=tmp_path)
        assert hook_path.exists()
        assert hook_path.name == "pre-commit"

    def test_install_hook_executable(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        hook_path = install_hook(repo_root=tmp_path)
        mode = hook_path.stat().st_mode
        assert mode & stat.S_IXUSR  # owner execute
        assert mode & stat.S_IXGRP  # group execute
        assert mode & stat.S_IXOTH  # others execute

    def test_hook_script_content(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        hook_path = install_hook(repo_root=tmp_path, fail_on="review", mode="full")
        content = hook_path.read_text()
        assert content.startswith("#!/bin/sh")
        assert HOOK_MARKER_START in content
        assert HOOK_MARKER_END in content
        assert "diff-guard check --staged --fail-on review" in content

    def test_install_replaces_existing(self, tmp_path: Path) -> None:
        hooks_dir = _make_git_hooks_dir(tmp_path)
        hook_path = hooks_dir / "pre-commit"

        # Write an initial diff-guard block.
        initial = generate_hook_script(fail_on="safe", mode="full")
        hook_path.write_text(initial)

        # Re-install with different settings.
        new_path = install_hook(repo_root=tmp_path, fail_on="danger", mode="test-only")
        content = new_path.read_text()

        assert "--fail-on safe" not in content
        assert "diff-guard test --staged --command-only" in content
        assert HOOK_MARKER_START in content

    def test_install_appends_to_existing_hook(self, tmp_path: Path) -> None:
        hooks_dir = _make_git_hooks_dir(tmp_path)
        hook_path = hooks_dir / "pre-commit"

        # Pre-existing hook content (no diff-guard markers).
        hook_path.write_text("#!/bin/sh\necho 'existing hook'\n")

        install_hook(repo_root=tmp_path)
        content = hook_path.read_text()

        assert "existing hook" in content
        assert HOOK_MARKER_START in content
        assert HOOK_MARKER_END in content


# ---------------------------------------------------------------------------
# uninstall_hook
# ---------------------------------------------------------------------------


class TestUninstallHook:
    def test_uninstall_hook_removes_block(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        install_hook(repo_root=tmp_path)
        assert is_hook_installed(repo_root=tmp_path)

        result = uninstall_hook(repo_root=tmp_path)
        assert result is True

        # File should be removed because it only contained the diff-guard block.
        hook_path = tmp_path / ".git" / "hooks" / "pre-commit"
        assert not hook_path.exists()

    def test_uninstall_preserves_existing(self, tmp_path: Path) -> None:
        hooks_dir = _make_git_hooks_dir(tmp_path)
        hook_path = hooks_dir / "pre-commit"

        # Write a hook with both external content and diff-guard block.
        other_content = "#!/bin/sh\necho 'other hook'\n"
        diff_guard_block = generate_hook_script()
        hook_path.write_text(other_content + "\n" + diff_guard_block)

        result = uninstall_hook(repo_root=tmp_path)
        assert result is True

        remaining = hook_path.read_text()
        assert "other hook" in remaining
        assert HOOK_MARKER_START not in remaining

    def test_uninstall_nonexistent(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        result = uninstall_hook(repo_root=tmp_path)
        assert result is False

    def test_uninstall_no_diff_guard_markers(self, tmp_path: Path) -> None:
        hooks_dir = _make_git_hooks_dir(tmp_path)
        hook_path = hooks_dir / "pre-commit"
        hook_path.write_text("#!/bin/sh\necho 'just a hook'\n")

        result = uninstall_hook(repo_root=tmp_path)
        assert result is False

        # Original content should be untouched.
        assert hook_path.exists()
        assert "just a hook" in hook_path.read_text()


# ---------------------------------------------------------------------------
# is_hook_installed
# ---------------------------------------------------------------------------


class TestIsHookInstalled:
    def test_is_hook_installed_true(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        install_hook(repo_root=tmp_path)
        assert is_hook_installed(repo_root=tmp_path) is True

    def test_is_hook_installed_false_no_file(self, tmp_path: Path) -> None:
        _make_git_hooks_dir(tmp_path)
        assert is_hook_installed(repo_root=tmp_path) is False

    def test_is_hook_installed_false_no_markers(self, tmp_path: Path) -> None:
        hooks_dir = _make_git_hooks_dir(tmp_path)
        hook_path = hooks_dir / "pre-commit"
        hook_path.write_text("#!/bin/sh\necho 'something else'\n")
        assert is_hook_installed(repo_root=tmp_path) is False

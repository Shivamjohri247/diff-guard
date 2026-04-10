"""Tests for .diff-guard-ignore file parsing and integration."""

from __future__ import annotations

from pathlib import Path

from diff_guard.utils.ignore_file import load_ignore_file


class TestLoadIgnoreFile:
    def test_parses_patterns(self, tmp_path: Path) -> None:
        ignore_file = tmp_path / ".diff-guard-ignore"
        ignore_file.write_text("*.log\n*.tmp\ndist/\n")
        patterns = load_ignore_file(tmp_path)
        assert patterns == ["*.log", "*.tmp", "dist/"]

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        ignore_file = tmp_path / ".diff-guard-ignore"
        ignore_file.write_text("# comment\n\n*.log\n  # another comment\n*.tmp\n")
        patterns = load_ignore_file(tmp_path)
        assert patterns == ["*.log", "*.tmp"]

    def test_negation_patterns(self, tmp_path: Path) -> None:
        ignore_file = tmp_path / ".diff-guard-ignore"
        ignore_file.write_text("*.py\n!important.py\n")
        patterns = load_ignore_file(tmp_path)
        assert patterns == ["*.py", "!important.py"]

    def test_empty_file(self, tmp_path: Path) -> None:
        ignore_file = tmp_path / ".diff-guard-ignore"
        ignore_file.write_text("")
        assert load_ignore_file(tmp_path) == []

    def test_missing_file(self, tmp_path: Path) -> None:
        assert load_ignore_file(tmp_path) == []

    def test_trailing_whitespace_stripped(self, tmp_path: Path) -> None:
        ignore_file = tmp_path / ".diff-guard-ignore"
        ignore_file.write_text("*.log   \n")
        patterns = load_ignore_file(tmp_path)
        assert patterns == ["*.log"]


class TestConfigIntegration:
    def test_ignore_file_merged_into_config(self, tmp_path: Path) -> None:
        from diff_guard.config import find_config

        # Create .diff-guard-ignore without .diff-guard.yml
        (tmp_path / ".diff-guard-ignore").write_text("*.generated.py\n*.auto.py\n")
        config = find_config(tmp_path)
        assert "*.generated.py" in config.ignore
        assert "*.auto.py" in config.ignore

    def test_ignore_file_combined_with_yml(self, tmp_path: Path) -> None:
        from diff_guard.config import find_config

        (tmp_path / ".diff-guard.yml").write_text("ignore:\n  - '*.lock'\n")
        (tmp_path / ".diff-guard-ignore").write_text("*.generated.py\n")
        config = find_config(tmp_path)
        assert "*.lock" in config.ignore
        assert "*.generated.py" in config.ignore

    def test_cli_ignore_overrides_all(self, tmp_path: Path) -> None:
        import fnmatch

        from diff_guard.config import find_config

        (tmp_path / ".diff-guard-ignore").write_text("*.py\n")
        config = find_config(tmp_path)

        # Simulate CLI --ignore in addition to config
        ignore_patterns = list(config.ignore) + ["*.js"]
        file_path = "app.js"
        assert any(fnmatch.fnmatch(file_path, p) for p in ignore_patterns)
        # .py files should also be ignored
        assert any(fnmatch.fnmatch("main.py", p) for p in ignore_patterns)

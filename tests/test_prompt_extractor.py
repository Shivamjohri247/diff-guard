from __future__ import annotations

from pathlib import Path

from diff_guard.models import ScopeConfig
from diff_guard.utils.prompt_extractor import find_prompt_file, read_prompt_file


class TestFindPromptFile:
    def test_finds_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / ".diff-guard-prompt").write_text("Be helpful")
        result = find_prompt_file(tmp_path)
        assert result is not None
        assert result.name == ".diff-guard-prompt"

    def test_returns_none_when_no_files(self, tmp_path: Path) -> None:
        result = find_prompt_file(tmp_path)
        assert result is None

    def test_uses_config_prompt_files(self, tmp_path: Path) -> None:
        (tmp_path / "custom_prompt.txt").write_text("Be concise")
        config = ScopeConfig(prompt_files=["custom_prompt.txt"])
        result = find_prompt_file(tmp_path, config)
        assert result is not None
        assert result.name == "custom_prompt.txt"

    def test_returns_first_match(self, tmp_path: Path) -> None:
        (tmp_path / ".cursorrules").write_text("first")
        (tmp_path / "custom.txt").write_text("second")
        config = ScopeConfig(prompt_files=["custom.txt", ".cursorrules"])
        result = find_prompt_file(tmp_path, config)
        assert result is not None
        assert result.name == "custom.txt"

    def test_skips_nonexistent(self, tmp_path: Path) -> None:
        (tmp_path / ".cursorrules").write_text("rules")
        config = ScopeConfig(prompt_files=["nonexistent.txt", ".cursorrules"])
        result = find_prompt_file(tmp_path, config)
        assert result is not None
        assert result.name == ".cursorrules"


class TestReadPromptFile:
    def test_reads_file(self, tmp_path: Path) -> None:
        f = tmp_path / "prompt.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_prompt_file(f) == "hello world"

    def test_returns_empty_on_missing(self, tmp_path: Path) -> None:
        result = read_prompt_file(tmp_path / "nonexistent.txt")
        assert result == ""

    def test_returns_empty_on_encoding_error(self, tmp_path: Path) -> None:
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x80\x81\x82")
        result = read_prompt_file(f)
        assert result == ""

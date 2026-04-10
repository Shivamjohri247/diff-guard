from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from diff_guard.core.scope_analyzer import ScopeResolver
from diff_guard.models import Change, ChangeType, DiffGuardConfig, ScopeConfig
from diff_guard.utils.prompt_extractor import find_prompt_file, read_prompt_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_change(file_path: str, functions: list[str] | None = None) -> Change:
    return Change(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        hunks=[],
        added_lines=1,
        removed_lines=0,
        functions_modified=functions or [],
    )


# ---------------------------------------------------------------------------
# prompt_extractor tests
# ---------------------------------------------------------------------------


class TestFindPromptFile:
    def test_finds_first_matching_file(self, tmp_path: Path) -> None:
        (tmp_path / ".diff-guard-prompt").write_text("scope: auth")
        result = find_prompt_file(tmp_path)
        assert result is not None
        assert result.name == ".diff-guard-prompt"

    def test_falls_back_to_second(self, tmp_path: Path) -> None:
        (tmp_path / ".claude-prompt").write_text("scope: auth")
        result = find_prompt_file(tmp_path)
        assert result is not None
        assert result.name == ".claude-prompt"

    def test_returns_none_when_no_files(self, tmp_path: Path) -> None:
        assert find_prompt_file(tmp_path) is None

    def test_custom_config_names(self, tmp_path: Path) -> None:
        (tmp_path / "custom-prompt.txt").write_text("hello")
        cfg = ScopeConfig(prompt_files=["custom-prompt.txt"])
        result = find_prompt_file(tmp_path, cfg)
        assert result is not None
        assert result.name == "custom-prompt.txt"


class TestReadPromptFile:
    def test_reads_content(self, tmp_path: Path) -> None:
        p = tmp_path / ".diff-guard-prompt"
        p.write_text("scope: authentication")
        assert read_prompt_file(p) == "scope: authentication"

    def test_returns_empty_on_missing(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent"
        assert read_prompt_file(p) == ""


# ---------------------------------------------------------------------------
# ScopeResolver priority tests
# ---------------------------------------------------------------------------


class TestScopeResolverPriority:
    def test_prompt_file_priority(self, tmp_path: Path) -> None:
        """Prompt file is used with confidence 1.0."""
        (tmp_path / ".diff-guard-prompt").write_text("fix auth/login.py validation")
        resolver = ScopeResolver(tmp_path)
        scope = resolver.resolve()
        assert scope.confidence == 1.0
        assert scope.source == "prompt_file"
        assert "auth/login.py" in scope.target_files

    def test_cli_arg_priority(self, tmp_path: Path) -> None:
        """CLI arg is used when no prompt file, confidence 0.8."""
        resolver = ScopeResolver(tmp_path)
        scope = resolver.resolve(cli_scope="modify auth/login.py")
        assert scope.confidence == 0.8
        assert scope.source == "cli"
        assert "auth/login.py" in scope.target_files

    def test_commit_message_fallback(self, tmp_path: Path) -> None:
        """Commit message is used when no prompt file and no CLI, confidence 0.6."""
        with patch(
            "diff_guard.utils.git.get_commit_message", return_value="fix login form validation"
        ):
            resolver = ScopeResolver(tmp_path)
            scope = resolver.resolve()
        assert scope.confidence == 0.6
        assert scope.source == "commit_message"

    def test_inference_priority(self, tmp_path: Path) -> None:
        """Inference from diff is used when no other signals, confidence 0.3."""
        resolver = ScopeResolver(tmp_path)
        changes = [
            _make_change("src/auth/login.py", ["validate_email"]),
            _make_change("src/auth/session.py", []),
        ]
        scope = resolver.resolve(changes=changes)
        assert scope.confidence == 0.3
        assert scope.source == "inferred"
        assert "src/auth/login.py" in scope.target_files
        assert "validate_email" in scope.target_functions

    def test_prompt_beats_cli(self, tmp_path: Path) -> None:
        """Prompt file takes priority over CLI arg."""
        (tmp_path / ".diff-guard-prompt").write_text("prompt file scope")
        resolver = ScopeResolver(tmp_path)
        scope = resolver.resolve(cli_scope="cli scope override")
        assert scope.confidence == 1.0
        assert scope.source == "prompt_file"
        assert "prompt file scope" in scope.description

    def test_cli_beats_commit(self, tmp_path: Path) -> None:
        """CLI arg takes priority over commit message."""
        with patch("diff_guard.utils.git.get_commit_message", return_value="commit msg"):
            resolver = ScopeResolver(tmp_path)
            scope = resolver.resolve(cli_scope="cli scope")
        assert scope.confidence == 0.8
        assert scope.source == "cli"

    def test_empty_scope_all_sources_fail(self, tmp_path: Path) -> None:
        """No signals at all returns minimal inferred scope, confidence 0.3."""
        resolver = ScopeResolver(tmp_path)
        with patch("diff_guard.utils.git.get_commit_message", return_value=""):
            scope = resolver.resolve()
        assert scope.confidence == 0.3
        assert scope.source == "inferred"
        assert scope.target_files == set()


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    def test_keyword_extraction(self, tmp_path: Path) -> None:
        """'fix login form validation' produces expected keywords."""
        resolver = ScopeResolver(tmp_path)
        keywords = resolver._extract_keywords("fix login form validation")
        assert "fix" in keywords
        assert "login" in keywords
        assert "form" in keywords
        assert "validation" in keywords

    def test_stop_words_filtered(self, tmp_path: Path) -> None:
        """Stop words are removed."""
        resolver = ScopeResolver(tmp_path)
        keywords = resolver._extract_keywords("the login is a form")
        assert "the" not in keywords
        assert "is" not in keywords
        assert "a" not in keywords
        assert "login" in keywords
        assert "form" in keywords


# ---------------------------------------------------------------------------
# Keyword-to-file mapping
# ---------------------------------------------------------------------------


class TestKeywordToFileMapping:
    def test_keyword_to_file_mapping(self, tmp_path: Path) -> None:
        """'login' keyword maps to files containing 'login' in path."""
        # Create a fake repo structure
        auth_dir = tmp_path / "src" / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "login.py").write_text("def login(): pass")
        (auth_dir / "session.py").write_text("def session(): pass")

        resolver = ScopeResolver(tmp_path)
        matched = resolver._map_keywords_to_files(["login"])
        # Should find login.py
        assert any("login.py" in f for f in matched)


# ---------------------------------------------------------------------------
# _parse_scope_text
# ---------------------------------------------------------------------------


class TestParseScopeText:
    def test_extracts_files(self, tmp_path: Path) -> None:
        """File-like patterns are extracted into target_files."""
        resolver = ScopeResolver(tmp_path)
        scope = resolver._parse_scope_text("modify auth/login.py and session.py")
        assert "auth/login.py" in scope.target_files
        assert "session.py" in scope.target_files

    def test_extracts_functions(self, tmp_path: Path) -> None:
        """Function-like patterns (word followed by ()) are extracted."""
        resolver = ScopeResolver(tmp_path)
        scope = resolver._parse_scope_text("fix validate_email() function")
        assert "validate_email" in scope.target_functions

    def test_extracts_concepts(self, tmp_path: Path) -> None:
        """Non-stop-word tokens become concepts."""
        resolver = ScopeResolver(tmp_path)
        scope = resolver._parse_scope_text("fix login form validation")
        assert "login" in scope.target_concepts
        assert "form" in scope.target_concepts
        assert "validation" in scope.target_concepts


# ---------------------------------------------------------------------------
# _enrich_with_project_areas
# ---------------------------------------------------------------------------


class TestEnrichWithProjectAreas:
    def test_enrich_with_project_areas(self, tmp_path: Path) -> None:
        """Scope mentioning 'auth' is expanded with related files from config."""
        cfg = DiffGuardConfig(
            scope=ScopeConfig(
                areas={
                    "auth": {
                        "files": ["src/auth/login.py", "src/auth/session.py"],
                        "related": ["tests/test_auth.py"],
                    }
                }
            )
        )
        resolver = ScopeResolver(tmp_path, config=cfg)
        scope = resolver._parse_scope_text("fix auth login")
        scope = resolver._enrich_with_project_areas(scope)
        assert "src/auth/login.py" in scope.target_files
        assert "src/auth/session.py" in scope.target_files
        assert "tests/test_auth.py" in scope.target_files

    def test_no_areas_no_change(self, tmp_path: Path) -> None:
        """Empty areas dict does not alter scope."""
        resolver = ScopeResolver(tmp_path)
        scope = resolver._parse_scope_text("fix login")
        original_files = set(scope.target_files)
        scope = resolver._enrich_with_project_areas(scope)
        assert scope.target_files == original_files

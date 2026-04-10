"""Tests for commit message quality checking."""

from __future__ import annotations

from diff_guard.core.commit_message_checker import check_commit_message
from diff_guard.models import Change, ChangeType


def _make_change(file_path: str, functions: list[str] | None = None) -> Change:
    return Change(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        hunks=[],
        added_lines=5,
        removed_lines=2,
        functions_modified=functions or [],
    )


class TestVagueMessages:
    def test_single_vague_word(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("fix", changes)
        assert result.is_vague
        assert result.score < 0.5

    def test_update_is_vague(self) -> None:
        changes = [_make_change("src/api/handlers.py")]
        result = check_commit_message("update", changes)
        assert result.is_vague

    def test_wip_is_vague(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("wip", changes)
        assert result.is_vague

    def test_good_message_not_vague(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("feat(auth): add OAuth2 login flow", changes)
        assert not result.is_vague
        assert result.score > 0.7


class TestLengthCheck:
    def test_short_message_flagged(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("hi", changes)
        assert any("too short" in issue for issue in result.issues)

    def test_long_enough_message(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("implement new authentication module for users", changes)
        assert not any("too short" in issue for issue in result.issues)


class TestScopeCorrelation:
    def test_message_mentions_changed_file(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("update login module", changes)
        assert not any("does not reference" in i for i in result.issues)

    def test_message_mentions_function(self) -> None:
        changes = [_make_change("src/utils.py", functions=["calculate_hash"])]
        result = check_commit_message("optimize calculate_hash performance", changes)
        assert not any("does not reference" in i for i in result.issues)

    def test_message_unrelated_to_changes(self) -> None:
        changes = [_make_change("src/payments/stripe.py")]
        result = check_commit_message("update documentation", changes)
        assert any("does not reference" in i for i in result.issues)


class TestConventionalCommit:
    def test_conventional_format_boosts_score(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("feat(auth): add OAuth2 login", changes)
        assert not any("conventional" in i.lower() for i in result.issues)

    def test_non_conventional_flagged(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("added a new thing to main", changes)
        assert any("conventional" in i.lower() for i in result.issues)


class TestEmptyMessage:
    def test_empty_message(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("", changes)
        assert result.score == 0.0
        assert result.is_vague

    def test_whitespace_only_message(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("   \n  ", changes)
        assert result.score == 0.0


class TestSuggestedImprovement:
    def test_suggests_for_low_score(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("fix", changes)
        assert result.suggested_improvement is not None
        assert (
            "auth" in result.suggested_improvement.lower()
            or "login" in result.suggested_improvement.lower()
        )

    def test_no_suggestion_for_high_score(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("feat(auth): add OAuth2 login flow", changes)
        assert result.suggested_improvement is None

    def test_suggestion_for_multiple_files(self) -> None:
        changes = [
            _make_change("src/auth/login.py"),
            _make_change("src/auth/session.py"),
            _make_change("src/auth/token.py"),
            _make_change("src/api/routes.py"),
        ]
        result = check_commit_message("wip", changes)
        assert result.suggested_improvement is not None


class TestScoring:
    def test_perfect_message(self) -> None:
        changes = [_make_change("src/auth/login.py")]
        result = check_commit_message("feat(auth): add OAuth2 login flow", changes)
        assert result.score >= 0.9

    def test_terrible_message(self) -> None:
        changes = [_make_change("src/payments/stripe.py")]
        result = check_commit_message("fix", changes)
        assert result.score <= 0.4

    def test_score_clamped_to_range(self) -> None:
        changes = [_make_change("src/main.py")]
        result = check_commit_message("good update to main", changes)
        assert 0.0 <= result.score <= 1.0

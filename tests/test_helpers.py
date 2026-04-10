from __future__ import annotations

from diff_guard.utils.helpers import format_file_path, pluralize


class TestFormatFilePath:
    def test_short_path_unchanged(self) -> None:
        assert format_file_path("src/app.py") == "src/app.py"

    def test_exact_max_width_unchanged(self) -> None:
        path = "a" * 60
        assert format_file_path(path) == path

    def test_long_path_truncated(self) -> None:
        path = "a" * 100
        result = format_file_path(path)
        assert len(result) == 60
        assert result.startswith("...")
        assert result.endswith(path[-57:])

    def test_custom_max_width(self) -> None:
        path = "abcdefghij"
        result = format_file_path(path, max_width=5)
        assert len(result) == 5
        assert result == "...ij"

    def test_empty_path(self) -> None:
        assert format_file_path("") == ""


class TestPluralize:
    def test_singular(self) -> None:
        assert pluralize(1, "file") == "file"

    def test_regular_plural(self) -> None:
        assert pluralize(2, "file") == "files"

    def test_zero_is_plural(self) -> None:
        assert pluralize(0, "file") == "files"

    def test_irregular_plural(self) -> None:
        assert pluralize(2, "mouse", "mice") == "mice"

    def test_negative_is_plural(self) -> None:
        assert pluralize(-1, "file") == "files"

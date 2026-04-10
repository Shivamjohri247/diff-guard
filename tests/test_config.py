from __future__ import annotations

import textwrap
from pathlib import Path

from diff_guard.config import (
    config_defaults,
    config_from_dict,
    find_config,
    generate_default_config,
    parse_yaml_simple,
)
from diff_guard.models import DiffGuardConfig, HookConfig, TestConfig, Thresholds


class TestParseYamlSimpleKeyValue:
    """parse_yaml_simple handles simple key-value pairs."""

    def test_string_value(self) -> None:
        result = parse_yaml_simple("name: hello")
        assert result == {"name": "hello"}

    def test_integer_value(self) -> None:
        result = parse_yaml_simple("count: 42")
        assert result == {"count": 42}

    def test_float_value(self) -> None:
        result = parse_yaml_simple("ratio: 0.6")
        assert result == {"ratio": 0.6}

    def test_boolean_true(self) -> None:
        result = parse_yaml_simple("enabled: true")
        assert result == {"enabled": True}

    def test_boolean_false(self) -> None:
        result = parse_yaml_simple("enabled: false")
        assert result == {"enabled": False}

    def test_quoted_double(self) -> None:
        result = parse_yaml_simple('message: "hello world"')
        assert result == {"message": "hello world"}

    def test_quoted_single(self) -> None:
        result = parse_yaml_simple("message: 'hello world'")
        assert result == {"message": "hello world"}

    def test_null_value(self) -> None:
        result = parse_yaml_simple("value: null")
        assert result == {"value": None}

    def test_multiple_keys(self) -> None:
        text = textwrap.dedent("""\
            name: test
            version: 1
            enabled: true
        """)
        result = parse_yaml_simple(text)
        assert result["name"] == "test"
        assert result["version"] == 1
        assert result["enabled"] is True


class TestParseYamlSimpleNested:
    """parse_yaml_simple handles nested structures via indentation."""

    def test_nested_dict(self) -> None:
        text = textwrap.dedent("""\
            parent:
              child: value
        """)
        result = parse_yaml_simple(text)
        assert isinstance(result["parent"], dict)
        assert result["parent"]["child"] == "value"

    def test_deeply_nested(self) -> None:
        text = textwrap.dedent("""\
            level1:
              level2:
                level3: deep
        """)
        result = parse_yaml_simple(text)
        assert result["level1"]["level2"]["level3"] == "deep"

    def test_multiple_nested_keys(self) -> None:
        text = textwrap.dedent("""\
            thresholds:
              phantom_relevance: 0.3
              risk_safe: 0.3
              risk_danger: 0.6
        """)
        result = parse_yaml_simple(text)
        t = result["thresholds"]
        assert isinstance(t, dict)
        assert t["phantom_relevance"] == 0.3
        assert t["risk_safe"] == 0.3
        assert t["risk_danger"] == 0.6


class TestParseYamlSimpleList:
    """parse_yaml_simple handles lists with - item syntax."""

    def test_simple_list(self) -> None:
        text = textwrap.dedent("""\
            items:
              - "a"
              - "b"
              - "c"
        """)
        result = parse_yaml_simple(text)
        assert isinstance(result["items"], list)
        assert result["items"] == ["a", "b", "c"]

    def test_list_with_unquoted_strings(self) -> None:
        text = textwrap.dedent("""\
            dirs:
              - tests/
              - src/
        """)
        result = parse_yaml_simple(text)
        assert isinstance(result["dirs"], list)
        assert "tests/" in result["dirs"]
        assert "src/" in result["dirs"]

    def test_mixed_values_after_key(self) -> None:
        text = textwrap.dedent("""\
            hook:
              fail_on: "danger"
              auto_test: false
              show_report: true
        """)
        result = parse_yaml_simple(text)
        hook = result["hook"]
        assert isinstance(hook, dict)
        assert hook["fail_on"] == "danger"
        assert hook["auto_test"] is False
        assert hook["show_report"] is True


class TestParseYamlSimpleFullConfig:
    """parse_yaml_simple parses a full .diff-guard.yml config."""

    def test_full_config(self) -> None:
        text = textwrap.dedent("""\
            # diff-guard configuration
            version: 1

            thresholds:
              phantom_relevance: 0.3
              risk_safe: 0.3
              risk_danger: 0.6

            ignore:
              - "*.lock"
              - "*.min.js"
              - "migrations/"

            tests:
              directories:
                - "tests/"
                - "test/"
              patterns:
                - "test_*.py"
                - "*_test.py"
              command: "pytest {files} -v"

            scope:
              prompt_files:
                - ".diff-guard-prompt"
                - ".claude-prompt"
              areas:
                auth:
                  files:
                    - "src/auth/"
                  related:
                    - "src/redis_cache.py"

            hook:
              fail_on: "danger"
              auto_test: false
              show_report: true
              mode: "full"

            languages:
              python:
                analyzer: "ast"
              javascript:
                analyzer: "regex"
        """)
        result = parse_yaml_simple(text)

        assert result["version"] == 1

        thresholds = result["thresholds"]
        assert isinstance(thresholds, dict)
        assert thresholds["phantom_relevance"] == 0.3
        assert thresholds["risk_safe"] == 0.3
        assert thresholds["risk_danger"] == 0.6

        assert isinstance(result["ignore"], list)
        assert "*.lock" in result["ignore"]

        tests = result["tests"]
        assert isinstance(tests, dict)
        assert isinstance(tests["directories"], list)
        assert "tests/" in tests["directories"]
        assert tests["command"] == "pytest {files} -v"

        scope = result["scope"]
        assert isinstance(scope, dict)
        assert isinstance(scope["prompt_files"], list)
        assert ".diff-guard-prompt" in scope["prompt_files"]

        assert isinstance(scope["areas"], dict)
        auth = scope["areas"]["auth"]
        assert isinstance(auth, dict)
        assert "src/auth/" in auth["files"]

        hook = result["hook"]
        assert isinstance(hook, dict)
        assert hook["fail_on"] == "danger"
        assert hook["auto_test"] is False

        langs = result["languages"]
        assert isinstance(langs, dict)
        assert langs["python"]["analyzer"] == "ast"

    def test_comment_lines_ignored(self) -> None:
        text = textwrap.dedent("""\
            # this is a comment
            key: value
            # another comment
        """)
        result = parse_yaml_simple(text)
        assert result == {"key": "value"}

    def test_inline_comment(self) -> None:
        text = textwrap.dedent("""\
            key: value # inline comment
        """)
        result = parse_yaml_simple(text)
        assert result["key"] == "value"


class TestConfigDefaults:
    """config_defaults returns a valid DiffGuardConfig."""

    def test_returns_config(self) -> None:
        config = config_defaults()
        assert isinstance(config, DiffGuardConfig)

    def test_has_thresholds(self) -> None:
        config = config_defaults()
        assert isinstance(config.thresholds, Thresholds)
        assert config.thresholds.phantom_relevance == 0.3
        assert config.thresholds.risk_safe == 0.3
        assert config.thresholds.risk_danger == 0.6

    def test_has_test_config(self) -> None:
        config = config_defaults()
        assert isinstance(config.tests, TestConfig)
        assert len(config.tests.directories) > 0
        assert "pytest" in config.tests.command

    def test_has_hook_config(self) -> None:
        config = config_defaults()
        assert isinstance(config.hook, HookConfig)
        assert config.hook.fail_on == "danger"


class TestConfigFromDict:
    """config_from_dict merges partial dict with defaults."""

    def test_partial_thresholds(self) -> None:
        data: dict[str, object] = {
            "thresholds": {"phantom_relevance": 0.5},
        }
        config = config_from_dict(data)
        assert config.thresholds.phantom_relevance == 0.5
        # Others should be defaults
        assert config.thresholds.risk_safe == 0.3
        assert config.thresholds.risk_danger == 0.6

    def test_empty_dict_returns_defaults(self) -> None:
        config = config_from_dict({})
        defaults = config_defaults()
        assert config.thresholds.phantom_relevance == defaults.thresholds.phantom_relevance
        assert config.tests.command == defaults.tests.command
        assert config.hook.fail_on == defaults.hook.fail_on

    def test_full_config_roundtrip(self) -> None:
        text = textwrap.dedent("""\
            thresholds:
              phantom_relevance: 0.4
              risk_safe: 0.2
              risk_danger: 0.7
            ignore:
              - "*.lock"
            tests:
              directories:
                - "tests/"
              command: "pytest {files}"
            hook:
              fail_on: "review"
              auto_test: true
        """)
        data = parse_yaml_simple(text)
        config = config_from_dict(data)
        assert config.thresholds.phantom_relevance == 0.4
        assert config.thresholds.risk_safe == 0.2
        assert config.thresholds.risk_danger == 0.7
        assert "*.lock" in config.ignore
        assert config.tests.directories == ["tests/"]
        assert config.tests.command == "pytest {files}"
        assert config.hook.fail_on == "review"
        assert config.hook.auto_test is True


class TestFindConfigMissing:
    """find_config returns defaults when no config file exists."""

    def test_missing_file(self, tmp_path: Path) -> None:
        config = find_config(tmp_path)
        defaults = config_defaults()
        assert config.thresholds.phantom_relevance == defaults.thresholds.phantom_relevance


class TestFindConfigPresent:
    """find_config loads an existing config file."""

    def test_present_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".diff-guard.yml"
        config_path.write_text(
            textwrap.dedent("""\
            thresholds:
              phantom_relevance: 0.5
        """)
        )
        config = find_config(tmp_path)
        assert config.thresholds.phantom_relevance == 0.5


class TestGenerateDefaultConfig:
    """generate_default_config generates a valid YAML string."""

    def test_generates_string(self) -> None:
        result = generate_default_config()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_output_is_parseable(self) -> None:
        result = generate_default_config()
        data = parse_yaml_simple(result)
        assert "thresholds" in data
        assert "tests" in data
        assert "hook" in data

    def test_roundtrip_defaults(self) -> None:
        """Generated config parses back to match defaults."""
        result = generate_default_config()
        data = parse_yaml_simple(result)
        config = config_from_dict(data)
        defaults = config_defaults()
        assert config.thresholds.phantom_relevance == defaults.thresholds.phantom_relevance
        assert config.thresholds.risk_safe == defaults.thresholds.risk_safe
        assert config.thresholds.risk_danger == defaults.thresholds.risk_danger
        assert config.hook.fail_on == defaults.hook.fail_on
        assert config.hook.auto_test == defaults.hook.auto_test
        assert config.tests.command == defaults.tests.command


class TestConfigWalkUp:
    """find_config walks up directories to find config."""

    def test_walk_up(self, tmp_path: Path) -> None:
        # Create config at root
        config_path = tmp_path / ".diff-guard.yml"
        config_path.write_text(
            textwrap.dedent("""\
            thresholds:
              phantom_relevance: 0.8
        """)
        )

        # Look from a subdirectory
        sub = tmp_path / "src" / "deep" / "nested"
        sub.mkdir(parents=True)

        config = find_config(sub)
        assert config.thresholds.phantom_relevance == 0.8

    def test_stops_at_boundary(self, tmp_path: Path) -> None:
        # Without any config files, should return defaults
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)
        config = find_config(sub)
        defaults = config_defaults()
        assert config.thresholds.phantom_relevance == defaults.thresholds.phantom_relevance

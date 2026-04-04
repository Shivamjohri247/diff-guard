from __future__ import annotations

import re
from pathlib import Path

from diff_guard.models import DiffGuardConfig, HookConfig, ScopeConfig, TestConfig, Thresholds


def parse_yaml_simple(text: str) -> dict[str, object]:
    """Minimal YAML subset parser using only stdlib.

    Handles: key: value, nested keys via indentation, lists with - item,
    quoted and unquoted strings, numbers, booleans.
    This covers the full .diff-guard.yml schema.
    """
    # First pass: identify line types and indent levels
    root: dict[str, object] = {}

    # Sentinel to distinguish "no inline value" from "null value"
    _NO_VALUE = object()

    # Pre-process lines into structured data
    parsed_lines: list[tuple[int, str, object]] = []  # (indent, type, data)
    # type is "key" -> data is (key_name, value_or_sentinel)
    # type is "list" -> data is item_value_str

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Check if it's a list item
        list_match = re.match(r"^(\s*)-\s+(.*)$", line)
        if list_match:
            item_value = _parse_value(list_match.group(2).strip())
            parsed_lines.append((indent, "list", item_value))
            continue

        # Check if it's a key: value pair
        kv_match = re.match(r"^(\s*)([\w][\w_-]*)\s*:\s*(.*)$", line)
        if kv_match:
            key = kv_match.group(2)
            value_str = kv_match.group(3).strip()
            if value_str == "" or value_str.startswith("#"):
                parsed_lines.append((indent, "key", (key, _NO_VALUE)))
            else:
                parsed_lines.append((indent, "key", (key, _parse_value(value_str))))
            continue

    # Second pass: build the tree using a recursive descent approach
    result = _build_tree(parsed_lines, 0, 0, _NO_VALUE)[0]
    if isinstance(result, dict):
        return result
    return root


def _build_tree(
    lines: list[tuple[int, str, object]],
    start: int,
    parent_indent: int,
    no_value_sentinel: object,
) -> tuple[dict[str, object], int]:
    """Recursively build a nested dict from parsed lines.

    Returns (result_dict, next_line_index).
    """
    result: dict[str, object] = {}
    i = start

    while i < len(lines):
        indent = lines[i][0]
        line_type = lines[i][1]
        data = lines[i][2]

        # If we've de-dented past our parent, we're done
        if indent < parent_indent and i > start:
            break

        if line_type == "key":
            assert isinstance(data, tuple)
            key_name = data[0]
            value = data[1]
            assert isinstance(key_name, str)
            if value is not no_value_sentinel:
                # Inline value (includes None for null, True/False, etc.)
                result[key_name] = value
                i += 1
            else:
                # This key has children (nested dict or list)
                # Look ahead to determine what comes next
                if i + 1 < len(lines):
                    next_indent = lines[i + 1][0]
                    next_type = lines[i + 1][1]
                    if next_indent > indent:
                        if next_type == "list":
                            # Collect all list items at the child indent level
                            items: list[object] = []
                            child_indent = next_indent
                            j = i + 1
                            while j < len(lines):
                                ci = lines[j][0]
                                ct = lines[j][1]
                                cd = lines[j][2]
                                if ci < child_indent:
                                    break
                                if ct == "list" and ci == child_indent:
                                    items.append(cd)
                                    j += 1
                                elif ct == "key" and ci == child_indent:
                                    # List of dicts (not needed for our schema)
                                    break
                                else:
                                    break
                            result[key_name] = items
                            i = j
                        elif next_type == "key":
                            # Nested dict
                            child_result, next_i = _build_tree(
                                lines, i + 1, next_indent, no_value_sentinel
                            )
                            result[key_name] = child_result
                            i = next_i
                    else:
                        # Empty value (key with no children at deeper indent)
                        result[key_name] = ""
                        i += 1
                else:
                    # Last line, empty value
                    result[key_name] = ""
                    i += 1
        elif line_type == "list":
            # List items at current level (shouldn't happen at root normally)
            i += 1
        else:
            i += 1

    return result, i


def _parse_value(value_str: str) -> object:
    """Parse a scalar YAML value string into a Python object."""
    if not value_str or value_str.startswith("#"):
        return ""

    # Strip inline comments (but not inside quotes)
    value_str = _strip_inline_comment(value_str)

    # Handle quoted strings
    if (value_str.startswith('"') and value_str.endswith('"')) or (
        value_str.startswith("'") and value_str.endswith("'")
    ):
        return value_str[1:-1]

    # Boolean
    if value_str.lower() in ("true", "yes", "on"):
        return True
    if value_str.lower() in ("false", "no", "off"):
        return False

    # Null
    if value_str.lower() in ("null", "~", "none"):
        return None

    # Integer
    try:
        return int(value_str)
    except ValueError:
        pass

    # Float
    try:
        return float(value_str)
    except ValueError:
        pass

    # Plain string
    return value_str


def _strip_inline_comment(value_str: str) -> str:
    """Strip inline comments from a value string, respecting quotes."""
    in_single = False
    in_double = False
    i = 0
    while i < len(value_str):
        ch = value_str[i]
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == "#" and not in_single and not in_double:
            # Check if preceded by a space (YAML comment requirement)
            if i > 0 and value_str[i - 1] == " ":
                return value_str[: i - 1].rstrip()
            elif i == 0:
                return ""
        i += 1
    return value_str


def config_defaults() -> DiffGuardConfig:
    """Return default configuration."""
    return DiffGuardConfig()


def config_from_dict(data: dict[str, object]) -> DiffGuardConfig:
    """Create DiffGuardConfig from a parsed YAML dict. Merges with defaults for missing fields."""
    defaults = config_defaults()

    # Thresholds
    thresholds_data = _as_dict(data.get("thresholds"))
    thresholds = Thresholds(
        phantom_relevance=_as_float(
            thresholds_data.get("phantom_relevance"),
            defaults.thresholds.phantom_relevance,
        ),
        risk_safe=_as_float(
            thresholds_data.get("risk_safe"),
            defaults.thresholds.risk_safe,
        ),
        risk_danger=_as_float(
            thresholds_data.get("risk_danger"),
            defaults.thresholds.risk_danger,
        ),
    )

    # Ignore
    ignore = _as_str_list(data.get("ignore"), defaults.ignore)

    # Tests
    tests_data = _as_dict(data.get("tests"))
    tests = TestConfig(
        directories=_as_str_list(tests_data.get("directories"), defaults.tests.directories),
        patterns=_as_str_list(tests_data.get("patterns"), defaults.tests.patterns),
        command=_as_str(tests_data.get("command"), defaults.tests.command),
    )

    # Scope
    scope_data = _as_dict(data.get("scope"))
    scope = ScopeConfig(
        prompt_files=_as_str_list(scope_data.get("prompt_files"), defaults.scope.prompt_files),
        areas=_as_areas(scope_data.get("areas"), defaults.scope.areas),
    )

    # Hook
    hook_data = _as_dict(data.get("hook"))
    hook = HookConfig(
        fail_on=_as_str(hook_data.get("fail_on"), defaults.hook.fail_on),
        auto_test=_as_bool(hook_data.get("auto_test"), defaults.hook.auto_test),
        show_report=_as_bool(hook_data.get("show_report"), defaults.hook.show_report),
        mode=_as_str(hook_data.get("mode"), defaults.hook.mode),
    )

    # Languages
    languages_data = data.get("languages")
    languages: dict[str, dict[str, str]] = defaults.languages.copy()
    if isinstance(languages_data, dict):
        for lang, lang_cfg in languages_data.items():
            if isinstance(lang_cfg, dict):
                str_cfg: dict[str, str] = {}
                for k, v in lang_cfg.items():
                    if isinstance(v, str):
                        str_cfg[k] = v
                languages[lang] = str_cfg

    return DiffGuardConfig(
        thresholds=thresholds,
        ignore=ignore,
        tests=tests,
        scope=scope,
        hook=hook,
        languages=languages,
    )


def _as_dict(value: object | None) -> dict[str, object]:
    """Cast value to dict or return empty dict."""
    if isinstance(value, dict):
        return value
    return {}


def _as_float(value: object | None, default: float) -> float:
    """Cast value to float or return default."""
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _as_str(value: object | None, default: str) -> str:
    """Cast value to str or return default."""
    if isinstance(value, str):
        return value
    return default


def _as_bool(value: object | None, default: bool) -> bool:
    """Cast value to bool or return default."""
    if isinstance(value, bool):
        return value
    return default


def _as_str_list(value: object | None, default: list[str]) -> list[str]:
    """Cast value to list of str or return default."""
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            else:
                result.append(str(item))
        return result
    return default


def _as_areas(
    value: object | None,
    default: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    """Parse the scope.areas config section."""
    if not isinstance(value, dict):
        return default
    result: dict[str, dict[str, list[str]]] = {}
    for area_name, area_cfg in value.items():
        if isinstance(area_cfg, dict):
            section: dict[str, list[str]] = {}
            for section_key, section_val in area_cfg.items():
                if isinstance(section_val, list):
                    str_items: list[str] = []
                    for item in section_val:
                        if isinstance(item, str):
                            str_items.append(item)
                        else:
                            str_items.append(str(item))
                    section[section_key] = str_items
            result[str(area_name)] = section
    return result


def find_config(repo_root: Path) -> DiffGuardConfig:
    """Walk up from repo_root to find .diff-guard.yml. Load it or return defaults."""
    current = repo_root.resolve()
    # Walk up at most 20 levels to avoid infinite loops at filesystem root
    for _ in range(20):
        config_path = current / ".diff-guard.yml"
        if config_path.is_file():
            text = config_path.read_text(encoding="utf-8")
            data = parse_yaml_simple(text)
            return config_from_dict(data)
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    return config_defaults()


def generate_default_config() -> str:
    """Generate a .diff-guard.yml string with all defaults and explanatory comments."""
    defaults = config_defaults()
    lines: list[str] = []
    a = lines.append

    a("# diff-guard configuration")
    a("# See https://github.com/diff-guard/diff-guard for full documentation")
    a("")
    a("version: 1")
    a("")

    a("# Risk thresholds (0.0 - 1.0)")
    a("thresholds:")
    a(f"  phantom_relevance: {defaults.thresholds.phantom_relevance}")
    a(f"  risk_safe: {defaults.thresholds.risk_safe}          # below this = safe")
    a(f"  risk_danger: {defaults.thresholds.risk_danger}         # above this = danger")
    a("")

    a("# Glob patterns for files to ignore during analysis")
    a("ignore:")
    a('  - "*.lock"')
    a('  - "*.min.js"')
    a('  - "*.min.css"')
    a('  - "node_modules/"')
    a('  - "vendor/"')
    a('  - "__pycache__/"')
    a('  - ".git/"')
    a('  - "migrations/"')
    a("")

    a("# Test discovery settings")
    a("tests:")
    a("  directories:")
    for d in defaults.tests.directories:
        a(f'    - "{d}"')
    a("  patterns:")
    for p in defaults.tests.patterns:
        a(f'    - "{p}"')
    a(f'  command: "{defaults.tests.command}"')
    a("")

    a("# Scope resolution settings")
    a("scope:")
    a("  prompt_files:")
    for pf in defaults.scope.prompt_files:
        a(f'    - "{pf}"')
    a("  # Define code areas for better scope detection")
    a("  # areas:")
    a("  #   auth:")
    a("  #     files:")
    a('  #       - "src/auth/"')
    a("  #     related:")
    a('  #       - "src/redis_cache.py"')
    a("")

    a("# Pre-commit hook settings")
    a("hook:")
    a(f'  fail_on: "{defaults.hook.fail_on}"     # safe | review | danger | never')
    a(f"  auto_test: {str(defaults.hook.auto_test).lower()}"
      "       # automatically run suggested tests")
    a(f"  show_report: {str(defaults.hook.show_report).lower()}"
      "    # show full report in hook output")
    a(f'  mode: "{defaults.hook.mode}"         # test-only | full | check-only')
    a("")

    a("# Language-specific analyzer settings")
    a("languages:")
    a("  python:")
    a('    analyzer: "ast"')
    a("  javascript:")
    a('    analyzer: "regex"')
    a("  typescript:")
    a('    analyzer: "regex"')
    a("  go:")
    a('    analyzer: "regex"')
    a("")

    return "\n".join(lines)

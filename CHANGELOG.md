# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-04-11

### Added

- **SARIF v2.1.0 reporter** (`--sarif`): CI/CD-ready output for GitHub Code Scanning and Azure DevOps with 4 rule IDs (DG001–DG004)
- **Commit message quality checker**: heuristic analysis for vagueness, length, scope correlation, and conventional-commit format
- **Disk-based FileGraph cache** (`.diff-guard-cache/graph.json`): mtime-based invalidation, survives across runs, auto-rebuilds on source changes
- **Multi-language import resolution**: JS/TS relative imports resolved from source file directory; Go, Rust, Java, Ruby, C/C++ import patterns via regex-based generic analyzer
- **`.diff-guard-ignore` file**: gitignore-style patterns merged into config ignore list
- **`scope.areas` config**: define code areas with related files for richer scope enrichment
- **Pre-commit config** (`.pre-commit-config.yaml`): ruff (lint + format), mypy, trailing-whitespace, end-of-file-fixer, check-yaml, check-added-large-files
- **CI pipeline hardening**: `ruff format --check`, expanded lint rules (B, SIM, C4), pip caching, coverage enforcement (80% threshold)

### Changed

- **CLI refactored**: `cmd_check` and `cmd_test` broken into focused helpers (`_parse_and_filter_changes`, `_check_commit_quality`, `_render_report`, `_exit_code_for_fail_on`, `_print_test_json`, `_print_test_human`)
- **SARIF `_build_results` split** into 4 per-rule methods for maintainability
- **`ScopeResolver`** now enriches scope via `config.scope.areas` definitions
- **`FileGraph`** discovers all source languages (not just Python); uses per-language analyzers
- **Directory ignore patterns** (ending in `/`) now correctly match files within via prefix matching, not just glob
- **100% similar renames** now correctly detected when `git diff` omits `---`/`+++` lines
- **Hook install** no longer duplicates `#!/bin/sh` shebangs on reinstall or when appending to existing hooks
- **All 14 model classes** have docstrings
- Source code cleaned of dead code (`IMPORT_PATTERNS`, `_discover_python_files`, stray comments)
- Expanded ruff lint rules: E, F, I, W, UP, B, SIM, C4
- 18 ruff lint violations fixed (SIM102, SIM105, SIM108, SIM110, B905, B007, E501, F821, F401)

### Fixed

- Pre-commit hook shebang duplication on reinstall
- Directory ignore patterns (`src/api/`) not matching files within (`src/api/users.py`)
- 100% similar file renames silently ignored by diff parser
- `load_cache()` crash on non-dict JSON values (null, lists)

### Tests

- **468 tests** (up from 260), **92% coverage**
- New test files: `test_cache`, `test_commit_message_checker`, `test_git`, `test_helpers`, `test_ignore_file`, `test_json_reporter`, `test_language_detector`, `test_markdown_reporter`, `test_models`, `test_pre_commit`, `test_prompt_extractor`, `test_sarif_reporter`
- Multi-language project fixture (Python + JS + TS)
- Comprehensive CLI E2E tests for all flag combinations and output formats

## [0.2.0] - 2026-04-05

### Changed

- Package renamed from `diff-guard` to `diffguard-cli` on PyPI (original name too similar to existing package)

## [0.1.0] - 2026-04-04

### Added

- **Core pipeline**: 6-stage analysis — diff parsing, scope resolution, phantom change detection, blast radius computation, regression risk scoring, reporting
- **CLI commands**: `check` (full blast radius analysis), `test` (test suggestions), `install` (pre-commit hook), `init` (config file generation)
- **Scope resolution**: 4-source priority chain — prompt file (1.0), CLI arg (0.8), commit message (0.6), diff inference (0.3)
- **Phantom change detection**: weighted relevance scoring (path + explicit + proximity + import-chain), import-chain whitelisting (2-hop), dynamic thresholds, auto-ignore for lockfiles/generated/migrations
- **Blast radius**: project-wide import graph with BFS downstream analysis (up to 3 hops), distance-based risk scoring, centrality scoring
- **Regression risk scoring**: 5-factor composite — scope overflow (0.30), complexity (0.20), centrality (0.20), test coverage (0.15), deletion risk (0.15)
- **Reporters**: terminal (ANSI colors, Unicode box-drawing), JSON, Markdown
- **Language analyzers**: AST-based Python analyzer (stdlib), regex-based generic fallback for Go/Rust/Java/Ruby/C/C++
- **Git hook**: install/uninstall with marker-based block management, configurable fail threshold and mode (test-only/full/check-only)
- **Configuration**: stdlib-only YAML parser for `.diff-guard.yml`, scope confidence gating (below 0.4 never blocks commits)
- **Zero mandatory dependencies**: core uses only Python stdlib
- **Optional deps**: tree-sitter for JS/TS, httpx for GitHub integration
- **Full type safety**: `mypy --strict` clean across 28 source files
- **Test suite**: 260 tests passing

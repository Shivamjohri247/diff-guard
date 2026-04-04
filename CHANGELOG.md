# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2025-04-04

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

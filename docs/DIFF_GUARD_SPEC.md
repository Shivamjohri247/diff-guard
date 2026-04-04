# diff-guard — Implementation Specification

## What to build

`diff-guard` is a CLI tool and git hook that analyzes code changes made by AI coding agents (Claude Code, Cursor, Copilot, Codex, Windsurf, Cline, etc.) and **detects unintended side effects before they're committed**. It computes the "blast radius" of every change — which files were touched that shouldn't have been, which functions are affected downstream, and which tests should be run to catch regressions.

The core insight: AI coding agents in 2026 run autonomously for minutes or hours, touching dozens of files. Research shows AI-generated code creates 1.7x more issues than human code. Developers report the "butterfly effect" — asking the AI to tweak a form layout and having unrelated features break silently. Existing code review tools (CodeRabbit, Greptile) analyze PRs after they're pushed. `diff-guard` catches problems **before the commit**, in the developer's local workflow, at the exact moment the AI finishes its changes.

---

## The gap

| Tool | What it does | What it misses |
|------|-------------|----------------|
| CodeRabbit | AI review on PRs after push | Too late — damage already committed and pushed |
| CodeScene | Tracks tech debt over time | Historical analysis, not real-time pre-commit guard |
| git-deps | Textual dependency between commits | No semantic understanding — can't detect logical coupling |
| tree-sitter blast-radius tools | Build call graphs from AST | Require complex setup; don't map to AI agent prompts |
| Blast Radius (Terraform) | Terraform dependency graphs | Infrastructure only, not application code |
| blast-radius.dev | Concept / early stage | Not shipped yet |

**Nobody has built**: a lightweight, pre-commit tool specifically designed for the AI agent workflow that compares what the AI was ASKED to do vs. what it ACTUALLY changed, flags the delta, and runs targeted tests.

---

## Project structure

```
diff-guard/
├── pyproject.toml
├── README.md
├── LICENSE                              # MIT
├── diff_guard/
│   ├── __init__.py                      # Public API
│   ├── cli.py                           # CLI entry point (argparse)
│   ├── config.py                        # DiffGuardConfig
│   ├── core/
│   │   ├── __init__.py
│   │   ├── diff_parser.py               # Parse git diff into structured change objects
│   │   ├── scope_analyzer.py            # Determine intended scope from prompt/commit msg
│   │   ├── blast_radius.py              # Compute downstream impact of changes
│   │   ├── phantom_change_detector.py   # Find changes to files NOT in the intended scope
│   │   ├── regression_risk_scorer.py    # Score each changed file for regression risk
│   │   └── test_mapper.py              # Map changed functions → relevant test files
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── python_analyzer.py           # Python: AST-based import/call graph
│   │   ├── javascript_analyzer.py       # JS/TS: import/require graph
│   │   ├── generic_analyzer.py          # Fallback: regex-based cross-file reference detection
│   │   └── language_detector.py         # Detect project language(s)
│   ├── reporters/
│   │   ├── __init__.py
│   │   ├── terminal_reporter.py         # Rich terminal output with colors and tables
│   │   ├── json_reporter.py             # Machine-readable JSON report
│   │   ├── markdown_reporter.py         # Markdown for PR comments
│   │   └── github_reporter.py           # Post as GitHub PR review comment
│   ├── hooks/
│   │   ├── __init__.py
│   │   ├── pre_commit.py                # Git pre-commit hook logic
│   │   └── install.py                   # `diff-guard install` — sets up git hooks
│   └── utils/
│       ├── __init__.py
│       ├── git.py                       # Git operations (diff, log, blame)
│       ├── file_graph.py                # Build project-wide file dependency graph
│       └── prompt_extractor.py          # Extract AI prompt from commit msg / session file
├── tests/
│   ├── conftest.py
│   ├── fixtures/                        # Sample git diffs and project structures
│   │   ├── simple_python_project/
│   │   ├── react_project/
│   │   └── sample_diffs/
│   ├── test_diff_parser.py
│   ├── test_scope_analyzer.py
│   ├── test_blast_radius.py
│   ├── test_phantom_changes.py
│   ├── test_regression_scorer.py
│   ├── test_test_mapper.py
│   └── test_cli.py
├── examples/
│   ├── basic_usage.sh                   # Shell script showing basic CLI usage
│   ├── pre_commit_setup.sh              # How to set up as git hook
│   └── ci_integration.yml               # GitHub Actions example
└── benchmarks/
    ├── sample_ai_diffs/                 # Real-world AI-generated diffs for testing
    └── run_benchmark.py
```

---

## 1. Core concepts

### Change object

Every file change in a diff is parsed into a structured `Change` object:

```python
@dataclass
class Change:
    file_path: str
    change_type: ChangeType          # ADDED | MODIFIED | DELETED | RENAMED
    hunks: list[Hunk]                # Individual diff hunks
    added_lines: int
    removed_lines: int
    functions_modified: list[str]    # Function/class names that were changed
    imports_modified: list[str]      # Import statements added/removed
    language: str                    # "python" | "javascript" | "typescript" | etc.
```

### IntendedScope

What the developer/AI was supposed to change:

```python
@dataclass
class IntendedScope:
    description: str                 # The original prompt or task description
    target_files: list[str]          # Files explicitly mentioned in the prompt
    target_functions: list[str]      # Functions/classes mentioned
    target_concepts: list[str]       # Keywords extracted (e.g., "auth", "login", "form")
    source: str                      # "commit_message" | "prompt_file" | "cli_arg" | "inferred"
```

### BlastRadiusReport

The final output:

```python
@dataclass
class BlastRadiusReport:
    # What was intended
    intended_scope: IntendedScope

    # What actually changed
    total_files_changed: int
    total_lines_changed: int
    changes: list[Change]

    # The interesting bits
    phantom_changes: list[PhantomChange]     # Changes outside intended scope
    downstream_affected: list[AffectedFile]  # Files not changed but potentially broken
    regression_risks: list[RegressionRisk]   # Scored risks
    suggested_tests: list[str]               # Test files/commands to run
    
    # Verdict
    risk_level: str                          # "safe" | "review" | "danger"
    risk_score: float                        # 0.0–1.0
```

### PhantomChange

A change that the AI made but probably shouldn't have:

```python
@dataclass
class PhantomChange:
    file_path: str
    reason: str                      # Why this is suspicious
    relevance_score: float           # 0.0–1.0, how related to the intended scope
    change_summary: str              # What was changed in this file
    severity: str                    # "info" | "warning" | "critical"
```

---

## 2. Core modules

### `diff_parser.py`

Parses `git diff --staged` (or `git diff HEAD~1`) into structured `Change` objects.

**Implementation:**
- Run `git diff --staged --unified=3 --stat` and `git diff --staged` to get both summary and full diff.
- Parse unified diff format: extract file paths, hunk headers (`@@ -line,count +line,count @@`), added/removed lines.
- For each changed file, also extract:
  - Modified function names: parse `@@` hunk headers which often contain the enclosing function name.
  - For Python: use `ast` module on the changed file to map line numbers → function/class names.
  - For JS/TS: regex match `function`, `const ... = () =>`, `class`, `export default`.
  - Modified imports: detect lines starting with `import`, `from ... import`, `require(`, `export`.

### `scope_analyzer.py`

Determines what the developer *intended* to change. This is the key differentiator — it connects the AI's prompt to the actual diff.

**Scope extraction priority (try in order):**
1. **CLI argument:** `diff-guard --scope "fix login form validation"` — developer passes it explicitly.
2. **Commit message:** Parse the staged commit message (if available via `git log --format=%B -1` or temp file).
3. **Prompt file:** Look for `.diff-guard-prompt` in the repo root — a file the AI agent can write to before making changes. Content: the original user prompt.
4. **CLAUDE.md / .cursorrules / .github/copilot-instructions.md:** Extract project-level context about what areas map to what files.
5. **Inference from diff:** If nothing else is available, infer scope from the most-changed file paths. The "root" of the change is the directory with the most modifications.

**Keyword extraction:**
- Extract nouns, verbs, and technical terms from the scope description.
- Map them to file paths using fuzzy matching against the project's file tree.
- Example: "fix login form validation" → target_concepts=["login", "form", "validation"] → likely files: `auth/login.py`, `forms/login_form.py`, `validators/`, `templates/login.html`.

### `blast_radius.py`

Compute downstream impact — files that weren't changed but could break.

**Algorithm:**
1. Build a project-wide file dependency graph (see `file_graph.py`).
2. For each changed file, find all files that import from it (direct dependents).
3. For each modified function/class, find all files that call or reference it (call graph).
4. Score each dependent by distance from the changed file (1-hop = high risk, 2-hop = medium, 3+ = low).
5. Return the list of `AffectedFile` objects with risk scores.

### `phantom_change_detector.py`

The heart of the tool. Identifies "butterfly effect" changes.

**Algorithm:**
1. Take the `IntendedScope` and the list of `Change` objects.
2. For each changed file, compute a **relevance score** to the intended scope:
   - **Path relevance:** Does the file path contain any of the target concepts? (e.g., `auth/login.py` is relevant to "login form")
   - **Explicit mention:** Was this file explicitly mentioned in the prompt?
   - **Proximity:** Is this file in the same directory as an explicitly-mentioned file?
   - **Import chain:** Is this file imported by a target file (1-hop = relevant, 2+ = less so)?
3. Files with relevance score below a threshold (default 0.3) are flagged as **phantom changes**.
4. For each phantom change, classify the severity:
   - **Critical:** File is in a completely unrelated directory AND has significant changes (>5 lines).
   - **Warning:** File is loosely related but not mentioned, OR only has minor changes in an unrelated file.
   - **Info:** File is a config file, lockfile, or auto-generated file that commonly changes as a side effect.

**Auto-ignore list** (configurable):
- `package-lock.json`, `yarn.lock`, `poetry.lock`, `Pipfile.lock`
- `*.pyc`, `__pycache__/`, `.DS_Store`
- Auto-generated files (detected by comments like "auto-generated", "do not edit")
- Files matching patterns in `.diff-guard-ignore`

### `regression_risk_scorer.py`

Score each change for regression risk.

**Risk factors (each 0.0–1.0, weighted sum):**
- **Scope overflow** (0.30 weight): How much of the change is outside intended scope.
- **Complexity of change** (0.20): Lines changed / cyclomatic complexity of modified functions.
- **Centrality** (0.20): How many other files depend on the changed files (from dependency graph).
- **Test coverage** (0.15): Whether the changed functions have corresponding test files (heuristic: look for `test_` prefix or `__tests__/` directory matches).
- **Deletion risk** (0.15): Ratio of deleted lines to added lines. High deletion = higher risk.

**Overall risk classification:**
- `safe` (score < 0.3): Changes look clean and within scope.
- `review` (score 0.3–0.6): Some changes outside scope, worth a quick look.
- `danger` (score > 0.6): Significant phantom changes or high centrality impact.

### `test_mapper.py`

Map changes to the most relevant test files to run.

**Strategy:**
1. For each changed file `src/auth/login.py`, look for:
   - `tests/test_login.py`, `tests/auth/test_login.py` (name-based)
   - `tests/test_auth.py` (directory-based)
   - Files that import the changed module (grep `from auth.login import` in test directories)
2. For each changed function `validate_email()`, look for:
   - Test functions named `test_validate_email` anywhere in the test directory.
3. Deduplicate and return ordered list.
4. Also return a suggested test command: `pytest tests/test_login.py tests/test_auth.py -v`

---

## 3. Language analyzers (`diff_guard/analyzers/`)

### `python_analyzer.py`

Uses Python's built-in `ast` module (zero external deps).

**Capabilities:**
- Parse imports: `import X`, `from X import Y`, relative imports.
- Build module dependency graph: file A imports from file B → edge A→B.
- Map line numbers to enclosing function/class using AST node visitor.
- Extract function signatures and call sites within a file.

### `javascript_analyzer.py`

Regex-based (no babel/esprima dependency for v1).

**Capabilities:**
- Parse imports: `import X from 'Y'`, `require('Y')`, `export { X } from 'Y'`.
- Detect `import()` dynamic imports.
- Detect component references in JSX: `<LoginForm />` → find `LoginForm` definition.
- Build file dependency graph from import statements.

### `generic_analyzer.py`

Fallback for any language.

**Capabilities:**
- Grep-based cross-file reference detection: find all files that contain the name of a changed function/class.
- File-path-based proximity: files in the same directory are considered related.
- No AST parsing — purely textual.

### `language_detector.py`

Detect the primary language(s) of the project.

- Look at file extensions in the diff.
- Check for `pyproject.toml` / `setup.py` → Python.
- Check for `package.json` → JavaScript/TypeScript.
- Check for `go.mod` → Go. `Cargo.toml` → Rust. `pom.xml` → Java.
- Return a ranked list of languages.

---

## 4. CLI (`diff_guard/cli.py`)

Uses `argparse` only (no click/typer).

### Commands

#### `diff-guard check`

The main command. Analyzes staged changes (or the last commit).

```
$ diff-guard check --scope "fix login form validation"

╭─────────────────────────────────────────────────────────╮
│                  diff-guard blast radius                │
├─────────────────────────────────────────────────────────┤
│  Scope: "fix login form validation"                     │
│  Files changed: 7  │  Lines: +142 / -38                 │
│  Risk level: ⚠️  REVIEW (score: 0.54)                   │
╰─────────────────────────────────────────────────────────╯

✅ In scope (4 files):
   src/auth/login.py           +45 / -12   validate_email(), validate_password()
   src/templates/login.html    +28 / -8    form layout, error messages
   src/forms/login_form.py     +15 / -3    field validators
   tests/test_login.py         +30 / -0    new test cases

⚠️  Phantom changes (2 files):
   src/auth/session.py         +18 / -9    create_session(), refresh_token()
   │  → Relevance: 0.22 — not mentioned in scope
   │  → Risk: session management could affect ALL authenticated routes
   │  → 14 files depend on this module
   │
   src/middleware/rate_limit.py +6 / -6     check_rate_limit()
   │  → Relevance: 0.08 — completely unrelated to login form
   │  → Risk: rate limiting affects every API endpoint
   │  → CRITICAL: 31 files depend on this module

💥 Downstream blast radius:
   src/api/users.py            imports session.py → may break
   src/api/payments.py         imports session.py → may break
   src/api/dashboard.py        imports session.py, rate_limit.py → may break
   ... and 22 more files

🧪 Suggested tests to run:
   pytest tests/test_login.py tests/test_session.py tests/test_rate_limit.py tests/api/ -v

💡 Recommendation: Review changes to session.py and rate_limit.py manually.
   These files are high-centrality and outside your stated scope.
```

**Flags:**
- `--scope "description"` — Explicitly state what you intended to change.
- `--staged` (default) — Analyze staged changes.
- `--last-commit` — Analyze the last commit instead.
- `--diff <ref>` — Analyze diff between current state and a git ref.
- `--json` — Output as JSON instead of terminal UI.
- `--markdown` — Output as markdown (for PR comments).
- `--fail-on danger` — Exit with code 1 if risk level is "danger" (for CI).
- `--fail-on review` — Exit with code 1 if risk level is "review" or higher.
- `--auto-test` — Automatically run the suggested test command.
- `--ignore <pattern>` — Additional file patterns to ignore.

#### `diff-guard install`

Install as a git pre-commit hook.

```
$ diff-guard install
✅ Installed diff-guard as pre-commit hook in .git/hooks/pre-commit
   Every commit will be checked. Use --no-verify to skip.
   Configure behavior in .diff-guard.yml
```

Creates `.git/hooks/pre-commit` that runs `diff-guard check --staged --fail-on danger`.

#### `diff-guard graph`

Visualize the project's file dependency graph (optional, nice-to-have).

```
$ diff-guard graph --output deps.svg
✅ Dependency graph saved to deps.svg (47 nodes, 123 edges)
```

#### `diff-guard init`

Create a `.diff-guard.yml` config file with sensible defaults.

```
$ diff-guard init
✅ Created .diff-guard.yml with default configuration
```

---

## 5. Configuration (`.diff-guard.yml`)

```yaml
# .diff-guard.yml
version: 1

# Risk thresholds
thresholds:
  phantom_relevance: 0.3       # Below this = flagged as phantom
  risk_safe: 0.3               # Below this = "safe"
  risk_danger: 0.6             # Above this = "danger"

# File patterns to always ignore (in addition to built-in list)
ignore:
  - "*.lock"
  - "*.min.js"
  - "*.min.css"
  - "migrations/"
  - "generated/"
  - "__snapshots__/"

# Test discovery
tests:
  directories: ["tests/", "test/", "__tests__/", "spec/"]
  patterns: ["test_*.py", "*.test.ts", "*.spec.js", "*_test.go"]
  command: "pytest {files} -v"       # Template for test command

# Scope inference
scope:
  # Files where the AI agent writes its prompt before making changes
  prompt_files:
    - ".diff-guard-prompt"
    - ".claude-prompt"
    - ".cursor-prompt"
  
  # Project area → file mapping for better scope inference
  areas:
    auth: ["src/auth/", "src/middleware/auth*"]
    payments: ["src/payments/", "src/billing/"]
    ui: ["src/components/", "src/templates/", "src/styles/"]

# Pre-commit hook behavior
hook:
  fail_on: "danger"              # "safe" | "review" | "danger" | "never"
  auto_test: false               # Run tests automatically
  show_report: true              # Show full report even for safe commits

# Language-specific settings
languages:
  python:
    analyzer: "ast"              # "ast" (built-in) or "tree-sitter" (requires dep)
  javascript:
    analyzer: "regex"            # "regex" (built-in) or "tree-sitter"
```

---

## 6. Integration with AI agents

### Claude Code integration

Claude Code supports `CLAUDE.md` for project instructions. Add to `CLAUDE.md`:

```markdown
## Before committing changes

After making changes, write a one-line description of what you changed
to the file `.diff-guard-prompt` before committing. Example:
echo "Refactored login form validation and added email format check" > .diff-guard-prompt
```

### Cursor / Windsurf / Copilot integration

These tools typically generate commits with descriptive messages. `diff-guard` extracts scope from the commit message automatically. No special setup needed.

### Generic integration

For any AI agent that exposes its prompt, write it to `.diff-guard-prompt`:

```bash
# In your agent wrapper script
echo "$USER_PROMPT" > .diff-guard-prompt
# Run the AI agent...
# Then:
diff-guard check --staged
```

---

## 7. Reporters (`diff_guard/reporters/`)

### `terminal_reporter.py`

Rich terminal output using only ANSI escape codes (no `rich` dependency).

- Color-coded sections: green for in-scope, yellow for warnings, red for danger.
- Box-drawing characters for the report frame.
- Progress-bar-style risk score visualization.
- Tree-view for downstream blast radius.

### `json_reporter.py`

Machine-readable JSON with the full `BlastRadiusReport` serialized.

### `markdown_reporter.py`

Markdown output suitable for pasting into PR descriptions or comments.

### `github_reporter.py` (stretch goal)

Posts the report as a GitHub PR review comment via the GitHub API.
Requires `GITHUB_TOKEN` env var.

---

## 8. pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "diff-guard"
version = "0.1.0"
description = "Blast radius analyzer for AI-generated code changes. Catches the butterfly effect before you commit."
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [{ name = "diff-guard contributors" }]
keywords = ["git", "diff", "ai", "coding-agent", "blast-radius", "code-review", "pre-commit"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Topic :: Software Development :: Quality Assurance",
]

# Zero mandatory external dependencies — uses only Python stdlib
dependencies = []

[project.optional-dependencies]
github = ["httpx>=0.27"]           # For GitHub PR comment posting
tree-sitter = [                     # For advanced AST analysis
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.22",
    "tree-sitter-javascript>=0.22",
    "tree-sitter-typescript>=0.22",
]
dev = ["pytest>=8.0", "ruff>=0.5", "mypy>=1.10"]

[project.scripts]
diff-guard = "diff_guard.cli:main"
```

**Key design choice**: ZERO mandatory dependencies. The core tool uses only Python stdlib (`ast`, `re`, `subprocess`, `json`, `pathlib`, `argparse`). This makes it install instantly and work everywhere.

---

## 9. Tests

### Fixtures

Create realistic test scenarios:

1. **`simple_python_project/`** — A small Flask app with auth, payments, and dashboard modules. Used to test dependency graph building and blast radius computation.

2. **`react_project/`** — A React app with components, hooks, and API calls. Used to test JavaScript import analysis.

3. **`sample_diffs/`** — Pre-recorded git diffs representing:
   - **Clean change:** Only touches files related to the stated scope. Should score "safe."
   - **Butterfly change:** Asked to fix a button, also modified the database schema. Should flag phantom changes.
   - **High-centrality change:** Modified a utility function used by 20+ files. Should flag high blast radius.
   - **Config-only side effect:** Changed `package.json` and lockfile alongside intended changes. Should auto-ignore.

### Test plan

- `test_diff_parser.py` — Parse sample diffs into correct Change objects.
- `test_scope_analyzer.py` — Extract scope from commit messages, prompt files, CLI args.
- `test_blast_radius.py` — Compute correct downstream files from dependency graph.
- `test_phantom_changes.py` — Flag correct files as phantom changes against known good/bad diffs.
- `test_regression_scorer.py` — Score known risky vs. safe changes correctly.
- `test_test_mapper.py` — Map changes to correct test files in sample projects.
- `test_cli.py` — CLI commands produce correct exit codes and output format.

---

## 10. README.md structure

1. **Hero** — "Stop AI coding agents from breaking things they weren't asked to touch." + badges.
2. **The problem** — 3-sentence summary with stats (1.7x more issues, butterfly effect quote).
3. **30-second demo** — Terminal recording / screenshot of the CLI output.
4. **Install** — `pip install diff-guard` + `diff-guard install` for git hook.
5. **How it works** — Scope → Diff → Blast radius → Report pipeline in prose.
6. **Configuration** — `.diff-guard.yml` reference.
7. **AI agent integration** — Claude Code, Cursor, Copilot, generic setup.
8. **CI/CD integration** — GitHub Actions example.
9. **Language support** — Python (AST), JS/TS (regex), others (generic).
10. **Contributing** — Standard guide.
11. **License** — MIT.

---

## 11. Implementation priorities

### Must-have for v0.1 (weekend scope)

1. `diff_parser.py` — parse `git diff` into Change objects
2. `scope_analyzer.py` — extract scope from CLI arg + commit message
3. `phantom_change_detector.py` — flag files outside intended scope
4. `python_analyzer.py` — AST-based import graph for Python projects
5. `generic_analyzer.py` — regex fallback for other languages
6. `blast_radius.py` — compute downstream affected files
7. `regression_risk_scorer.py` — score and classify risk
8. `test_mapper.py` — map changes to test files
9. `terminal_reporter.py` — pretty CLI output
10. `cli.py` — `check` and `install` commands
11. `pre_commit.py` — git hook
12. Core tests with sample fixtures
13. README.md
14. Zero-dep `pyproject.toml`

### Nice-to-have for v0.2

1. `javascript_analyzer.py` — full JS/TS import analysis
2. `json_reporter.py` + `markdown_reporter.py`
3. `github_reporter.py` — post to PRs
4. `.diff-guard.yml` config file support
5. `diff-guard graph` command with SVG output
6. tree-sitter-based analyzers for more languages
7. `--auto-test` flag that runs suggested tests
8. MCP server: expose diff-guard as a tool that AI agents can call to self-check
9. VS Code extension that shows blast radius inline
10. Prompt file integration with Claude Code / Cursor

---

## 12. Design principles

1. **Zero dependencies in core.** The tool must install with `pip install diff-guard` and work immediately. All analysis uses Python stdlib only (`ast`, `re`, `subprocess`, `pathlib`). Optional deps (tree-sitter, httpx) are extras.

2. **Git-native.** The tool works with `git diff` output. No custom VCS integrations. If it's in git, it works.

3. **The scope comparison is the killer feature.** Without knowing what the AI was ASKED to do, you can't know what's a phantom change. This is what separates diff-guard from generic static analysis tools. Every design decision should reinforce this.

4. **Fast.** The tool must run in under 2 seconds on a typical project (< 1000 files). No LLM calls. No network requests (except optional GitHub posting). Pure local computation.

5. **Conservative defaults.** Only flag "danger" by default. Don't cry wolf. A tool that blocks every commit gets turned off immediately.

6. **Agent-friendly.** Design for the world where AI agents write `.diff-guard-prompt` before committing. This is the bridge between the agent's intent and the tool's analysis.

7. **Incremental adoption.** Works without any config file. Works without knowing the scope (falls back to heuristic inference). Works on any language (falls back to generic analyzer). Each layer of configuration makes it more accurate, but it's useful from minute one.

8. **Type hints everywhere.** Full `mypy --strict` compliance. `from __future__ import annotations` in every file.

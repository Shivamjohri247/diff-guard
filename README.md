# diff-guard

[![PyPI version](https://img.shields.io/pypi/v/diffguard-cli.svg)](https://pypi.org/project/diffguard-cli/)

**Stop AI coding agents from breaking things they weren't asked to touch.**

diff-guard is a blast radius analyzer for AI-generated code changes. It detects unintended modifications, measures their downstream impact, and blocks dangerous commits before they reach production.

---

## The Problem

AI coding agents are fast, but they create **1.7x more post-release issues** than human-written code. An agent asked to fix a login bug might also refactor the payment module, tweak a cache layer, or silently change error handling three files away.

The butterfly effect is real: one stray change in a utility function can cascade through import chains, breaking features nobody asked it to touch. Traditional linters and tests catch syntax errors and known patterns, but they don't answer the question: **"Did the AI change more than it was supposed to?"**

diff-guard answers that question. Every commit.

---

## 30-Second Demo

```bash
$ diffguard-cli check --scope "fix login form validation"

╭──────────────────────────────────────────────────────────╮
│                 diff-guard blast radius                  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Scope: "fix login form validation"                      │
│         Files changed: 7  |  Lines: +142 / -38           │
╰──────────────────────────────────────────────────────────╯

Risk level: ⚠️  REVIEW (score: 0.54)
  [████████████░░░░░░░░░░] 54%

✅ In scope (4 files):
   src/auth/login.py           +45 / -12   validate_email(), validate_password()
   src/templates/login.html    +28 / -8    form layout, error messages
   src/forms/login_form.py     +15 / -3    field validators
   tests/test_login.py         +30 / -0    new test cases

⚠️  Phantom changes (2 files):
   src/auth/session.py         +18 / -9    [confidence: 72%]
   │  → Not mentioned in scope, but 1 hop from login.py via imports
   │  → Might be intentional — review recommended

   src/middleware/rate_limit.py +6 / -6     [confidence: 94%]
   │  → 0 import-chain connection to any in-scope file
   │  → Completely unrelated to "fix login form validation"
   │  → LIKELY UNINTENDED

💥 Downstream blast radius:
   src/api/users.py            imports session.py → may break
   src/api/payments.py         imports session.py → may break
   src/api/dashboard.py        imports session.py, rate_limit.py → may break
   ... and 22 more files

🧪 Suggested tests to run:
   pytest tests/test_login.py tests/test_session.py tests/test_rate_limit.py -v

💡 Recommendation: Review changes to session.py and rate_limit.py manually.
```

---

## Install

```bash
pip install diffguard-cli
```

> View on [PyPI](https://pypi.org/project/diffguard-cli/)

Then set up the pre-commit hook:

```bash
diffguard-cli install
```

Every commit will now be automatically checked. Use `--no-verify` to skip when needed.

---

## How It Works — The Pipeline

Every time you (or an AI agent) run `git commit`, diff-guard runs a 6-stage pipeline:

```
 git commit
     │
     ▼
 ┌──────────────────────────────────────────────────┐
 │  STAGE 1: DIFF PARSING                           │
 │  git diff --staged → list of Change objects      │
 │  (files, hunks, functions, imports, line counts) │
 └──────────┬───────────────────────────────────────┘
            │
            ▼
 ┌──────────────────────────────────────────────────┐
 │  STAGE 2: SCOPE RESOLUTION                       │
 │  "What was the developer/AI SUPPOSED to change?" │
 │  Try in priority order:                          │
 │   1. Prompt file (.diff-guard-prompt)  → conf 1.0│
 │   2. CLI argument (--scope)            → conf 0.8│
 │   3. Commit message                    → conf 0.6│
 │   4. Inference from diff structure    → conf 0.3│
 └──────────┬───────────────────────────────────────┘
            │
            ▼
 ┌──────────────────────────────────────────────────┐
 │  STAGE 3: PHANTOM CHANGE DETECTION               │
 │  For each changed file vs. scope:                │
 │   - Auto-ignore lockfiles, generated, migrations │
 │   - Import-chain whitelisting (2-hop)            │
 │   - Dynamic thresholds (low confidence → lenient)│
 │   - Relevance scoring (path + import + proximity)│
 │  "Did the AI change files it wasn't asked to?"   │
 └──────────┬───────────────────────────────────────┘
            │
            ▼
 ┌──────────────────────────────────────────────────┐
 │  STAGE 4: BLAST RADIUS                           │
 │  Build project import graph → BFS from changed   │
 │  files → find downstream dependents (up to 3 hops│
 │  "What ELSE could break?"                        │
 └──────────┬───────────────────────────────────────┘
            │
            ▼
 ┌──────────────────────────────────────────────────┐
 │  STAGE 5: RISK SCORING (5 weighted factors)      │
 │   Scope overflow   (0.30)                        │
 │ + Complexity       (0.20)                        │
 │ + Centrality       (0.20)                        │
 │ + Test coverage    (0.15)                        │
 │ + Deletion risk    (0.15)                        │
 │ ─────────────────────                            │
 │ = SAFE (<0.3) | REVIEW (0.3-0.6) | DANGER (>0.6)│
 │                                                  │
 │ Safety gate: scope confidence < 0.4              │
 │   → never exit non-zero (cannot block commits)   │
 └──────────┬───────────────────────────────────────┘
            │
            ▼
 ┌──────────────────────────────────────────────────┐
 │  STAGE 6: REPORT                                 │
 │  Terminal (ANSI colors) / JSON / Markdown         │
 │  + Test suggestions + Recommendation              │
 └──────────┬───────────────────────────────────────┘
            │
            ▼
      Exit 0 (safe) or Exit 1 (blocked)
```

---

## Commands

### `diffguard-cli check`

Full blast radius analysis of code changes.

```bash
# Check staged changes (default)
diffguard-cli check

# Check with explicit scope
diffguard-cli check --scope "add user authentication"

# Check last commit
diffguard-cli check --last-commit

# Check diff against a branch
diffguard-cli check --diff main

# Output formats
diffguard-cli check --json
diffguard-cli check --markdown

# Fail on specific risk level
diffguard-cli check --fail-on review
```

### `diffguard-cli test`

Suggest tests for changed files. Zero false-positive risk — purely maps changes to tests.

```bash
# Suggest tests for staged changes
diffguard-cli test

# Get just the test command
diffguard-cli test --command-only

# JSON output
diffguard-cli test --json
```

### `diffguard-cli install`

Install as a git pre-commit hook.

```bash
# Install with defaults (fail on 'danger')
diffguard-cli install

# Stricter: fail on 'review'
diffguard-cli install --fail-on review

# Test-only mode (just suggest tests, never block)
diffguard-cli install --mode test-only

# Uninstall
diffguard-cli install --uninstall
```

### `diffguard-cli init`

Create a `.diff-guard.yml` config file with sensible defaults.

```bash
diffguard-cli init
```

---

## AI Agent Integration

### Claude Code

Add this to your `CLAUDE.md`:

```markdown
## Before committing changes

After making changes, write a one-line description of what you changed
to the file `.diff-guard-prompt` before committing. Example:
echo "Refactored login form validation" > .diff-guard-prompt
```

When `.diff-guard-prompt` exists, diff-guard uses it as the scope source
with **confidence 1.0** — the most accurate phantom detection possible.

```
1. You ask Claude Code: "Fix the login form validation"
2. Claude Code edits files...
3. Claude Code writes scope:
   echo "fix login form validation" > .diff-guard-prompt
4. Claude Code commits:
   git add -A && git commit -m "fix login validation"
5. Hook fires → reads .diff-guard-prompt → detects phantom changes
   → blocks or allows the commit
```

### Cursor

Cursor writes descriptive commit messages. diff-guard extracts scope from
the commit message at confidence 0.6:

```
1. You highlight code: "Fix the payment calculation bug"
2. Cursor edits files (possibly touching unrelated files)...
3. Cursor commits: "Fix payment calculation bug in stripe.py"
4. Hook fires → reads commit message → detects phantom changes
```

For better accuracy, configure Cursor to write `.cursor-prompt` before
committing (diff-guard reads this file too, at confidence 1.0).

### Windsurf / Copilot / Cline / Any Agent

The same pattern works for any AI coding agent that can write to a file:

```bash
# In your agent instructions or wrapper script:
echo "$TASK_DESCRIPTION" > .diff-guard-prompt

# Agent does its work...

# Agent commits:
git add -A && git commit -m "changes"
# Hook fires automatically
```

### Scope Confidence Comparison

| Source | Confidence | Phantom Detection Accuracy |
|--------|-----------|---------------------------|
| `.diff-guard-prompt` | 1.0 | Very accurate |
| `--scope` CLI arg | 0.8 | Accurate |
| Commit message | 0.6 | Good |
| Inference from diff | 0.3 | Lenient (fewer flags) |

---

## Configuration

diff-guard reads `.diff-guard.yml` from your repository root.
Generate one with `diffguard-cli init`.

```yaml
# diff-guard configuration
version: 1

# Risk thresholds (0.0 - 1.0)
thresholds:
  phantom_relevance: 0.3   # min relevance to flag as phantom
  risk_safe: 0.3            # below this = safe
  risk_danger: 0.6          # above this = danger

# Glob patterns for files to ignore during analysis
ignore:
  - "*.lock"
  - "*.min.js"
  - "*.min.css"
  - "node_modules/"
  - "vendor/"
  - "__pycache__/"
  - ".git/"
  - "migrations/"

# Test discovery settings
tests:
  directories:
    - "tests/"
    - "test/"
    - "__tests__/"
    - "spec/"
  patterns:
    - "test_*.py"
    - "*_test.py"
    - "*.test.ts"
    - "*.test.js"
    - "*.spec.js"
  command: "pytest {files} -v"

# Scope resolution settings
scope:
  prompt_files:
    - ".diff-guard-prompt"
    - ".claude-prompt"
    - ".cursor-prompt"
  # Define code areas for better scope detection
  # areas:
  #   auth:
  #     files:
  #       - "src/auth/"
  #     related:
  #       - "src/redis_cache.py"

# Pre-commit hook settings
hook:
  fail_on: "danger"     # safe | review | danger | never
  auto_test: false       # automatically run suggested tests
  show_report: true      # show full report in hook output
  mode: "full"           # test-only | full | check-only

# Language-specific analyzer settings
languages:
  python:
    analyzer: "ast"
  javascript:
    analyzer: "regex"
  typescript:
    analyzer: "regex"
  go:
    analyzer: "regex"
```

---

## CI/CD Integration

### GitHub Actions

Add `.github/workflows/diff-guard.yml`:

```yaml
name: diff-guard
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  blast-radius-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install diffguard-cli

      - name: Check blast radius
        run: |
          diffguard-cli check \
            --diff origin/${{ github.base_ref }} \
            --fail-on review \
            --markdown \
            > diff-guard-report.md

      - name: Comment PR with report
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('diff-guard-report.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });

      - name: Suggest tests
        if: always()
        run: |
          diffguard-cli test \
            --diff origin/${{ github.base_ref }} \
            --json
```

---

## Language Support

| Language | Strategy | Notes |
|----------|----------|-------|
| Python | AST (stdlib) | Full import graph, function mapping |
| JavaScript/TypeScript | Generic (regex) | Full support with `pip install diffguard-cli[js]` (tree-sitter) |
| Go | Generic (regex) | Import patterns + function detection |
| Rust | Generic (regex) | `use` statements + `fn` detection |
| Java | Generic (regex) | Import + method detection |
| Ruby | Generic (regex) | `require` + `def` detection |
| C/C++ | Generic (regex) | `#include` detection |
| Any other | Generic fallback | Path-based proximity analysis |

---

## Quick Reference

| What | Command |
|------|---------|
| Install hook | `diffguard-cli install` |
| Stricter hook | `diffguard-cli install --fail-on review` |
| Test-only hook | `diffguard-cli install --mode test-only` |
| Uninstall hook | `diffguard-cli install --uninstall` |
| Check staged | `diffguard-cli check` |
| Check with scope | `diffguard-cli check --scope "fix auth"` |
| Check last commit | `diffguard-cli check --last-commit` |
| Check vs branch | `diffguard-cli check --diff main` |
| JSON for scripts | `diffguard-cli check --json` |
| Markdown for PR | `diffguard-cli check --markdown` |
| Suggest tests | `diffguard-cli test` |
| Just test command | `diffguard-cli test --command-only` |
| Create config | `diffguard-cli init` |
| Skip hook | `git commit --no-verify` |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b my-feature`
3. Make changes and add tests
4. Run checks: `pytest && mypy src/ --strict && ruff check src/`
5. Commit (diff-guard will check your changes!)
6. Open a pull request

---

## License

MIT

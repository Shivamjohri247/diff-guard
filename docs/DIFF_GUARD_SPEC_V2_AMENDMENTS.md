# diff-guard v2 — Spec Amendments (post-critique)

This document contains targeted amendments to `DIFF_GUARD_SPEC.md` based on expert critique. Pass BOTH files to Claude Code — the original spec is the base, this file overrides specific sections.

---

## Amendment 1: Restructured dependency strategy

### Problem identified
> "Regex for JS/TS is a trap. In the modern JS ecosystem (dynamic imports, aliased paths, barrel files, JSX/TSX), regex will break quickly."

### Resolution: Two-tier dependency model

**Core (zero deps):** Python-only analysis via `ast` module. Works perfectly, ships instantly.

**Recommended (lightweight deps):** `tree-sitter` + language grammars for JS/TS/Go/Rust/Java. Tree-sitter now ships pre-compiled binary wheels — no C compiler needed. The `tree-sitter` package itself has zero library dependencies. This makes it practical as a "recommended" (not optional) dependency for any project using JS/TS.

**Updated `pyproject.toml`:**

```toml
dependencies = []  # ZERO for pure-Python projects

[project.optional-dependencies]
js = [
    "tree-sitter>=0.22",
    "tree-sitter-javascript>=0.22",
    "tree-sitter-typescript>=0.22",
]
full = [
    "tree-sitter>=0.22",
    "tree-sitter-javascript>=0.22",
    "tree-sitter-typescript>=0.22",
    "tree-sitter-python>=0.22",
    "tree-sitter-go>=0.22",
]
github = ["httpx>=0.27"]
dev = ["pytest>=8.0", "ruff>=0.5", "mypy>=1.10"]
```

**Updated install instructions:**

```bash
# Python-only projects (zero deps)
pip install diff-guard

# JS/TS projects (recommended — pre-compiled wheels, no compiler needed)
pip install diff-guard[js]

# All languages
pip install diff-guard[full]
```

**Updated analyzer selection logic (`language_detector.py`):**

```python
def get_analyzer(language: str, config: DiffGuardConfig) -> BaseAnalyzer:
    if language == "python":
        return PythonASTAnalyzer()       # Always available, uses stdlib ast

    if language in ("javascript", "typescript", "jsx", "tsx"):
        try:
            import tree_sitter_javascript
            return TreeSitterJSAnalyzer()  # Accurate: handles aliases, barrel files, dynamic imports
        except ImportError:
            warnings.warn(
                "JS/TS analysis without tree-sitter is limited. "
                "Install with: pip install diff-guard[js]",
                DiffGuardWarning,
            )
            return GenericAnalyzer()       # Fallback: grep-based, will miss aliased imports

    # Go, Rust, Java, etc. — try tree-sitter, fall back to generic
    try:
        return TreeSitterAnalyzer(language)
    except ImportError:
        return GenericAnalyzer()
```

**Key decision:** If a JS/TS project is detected and tree-sitter is NOT installed, diff-guard prints a one-time warning but still runs with the generic analyzer. It never fails or refuses to run.

---

## Amendment 2: Scope inference — happy path first, fuzzy match last

### Problem identified
> "Heuristic scope inference will be noisy. If a developer asks the AI to 'update user session handling,' and the AI correctly touches `src/redis_cache.py`, your tool might flag it as a phantom change."

### Resolution: Layered scope resolution with explicit > implicit

The scope analyzer now uses a strict priority chain. Each level is more accurate but less available. The tool uses the BEST available source and never falls through to fuzzy inference if a better signal exists.

**Updated `scope_analyzer.py` — Resolution priority:**

```python
class ScopeResolver:
    """Resolves intended scope using a strict priority chain.
    Each level adds confidence. Higher confidence = fewer false positives."""

    def resolve(self, staged_diff: list[Change]) -> IntendedScope:
        # Priority 1 (confidence=1.0): Explicit prompt file
        # The AI agent writes its exact prompt before committing.
        scope = self._from_prompt_file()
        if scope:
            scope.confidence = 1.0
            scope.source = "prompt_file"
            return self._enrich_with_project_areas(scope)

        # Priority 2 (confidence=0.8): CLI argument
        # Developer passes --scope "fix login form validation"
        scope = self._from_cli_arg()
        if scope:
            scope.confidence = 0.8
            scope.source = "cli_arg"
            return self._enrich_with_project_areas(scope)

        # Priority 3 (confidence=0.6): Commit message
        # Parse the staged commit message (if using conventional commits, even better)
        scope = self._from_commit_message()
        if scope:
            scope.confidence = 0.6
            scope.source = "commit_message"
            return self._enrich_with_project_areas(scope)

        # Priority 4 (confidence=0.3): Inference from diff structure
        # ONLY used when nothing better is available.
        # Uses the MOST-changed directory as the "root" of intent.
        # Phantom detection thresholds are RELAXED at this confidence level.
        scope = self._infer_from_diff(staged_diff)
        scope.confidence = 0.3
        scope.source = "inferred"
        return scope
```

**Critical behavior change:** The phantom change detector adjusts its sensitivity based on scope confidence:

```python
def detect_phantoms(changes: list[Change], scope: IntendedScope, config: DiffGuardConfig) -> list[PhantomChange]:
    # Dynamic threshold: less confident scope = higher bar for flagging
    effective_threshold = config.phantom_relevance_threshold
    if scope.confidence < 0.5:
        effective_threshold *= 1.5   # Be MORE lenient when scope is inferred
    if scope.confidence < 0.4:
        effective_threshold *= 2.0   # Very lenient — only flag truly unrelated files
    ...
```

**The `_enrich_with_project_areas()` method** solves the redis_cache example:

```yaml
# .diff-guard.yml — project area mapping
areas:
  auth:
    files: ["src/auth/", "src/middleware/auth*"]
    related: ["src/redis_cache.py", "src/session/"]    # <-- THIS
  payments:
    files: ["src/payments/", "src/billing/"]
    related: ["src/stripe_client.py"]
```

When the scope mentions "session handling" and the project config says redis_cache is related to auth/session, the tool correctly includes it in the intended scope. Without this config, the tool falls back to import-chain analysis — if `session.py` imports `redis_cache`, it's 1-hop related and won't be flagged.

**Recommendation for spec consumers (Claude Code):** Implement Priority 1 (prompt file) and Priority 3 (commit message) first. Priority 4 (inference) is lowest priority and should only be built if time permits. The tool is MORE useful with a clear "write your prompt to .diff-guard-prompt" requirement than with a fuzzy inference system that generates false positives.

---

## Amendment 3: Anti-cry-wolf system

### Problem identified
> "Developers will bypass a tool that generates too many false positives. Balancing thresholds will be the hardest part."

### Resolution: Multi-layered false positive suppression

**3a. Semantic import-chain whitelisting**

Before flagging any file as a phantom, check if it's reachable within 2 hops in the import/dependency graph from ANY file in the intended scope. If yes, it's NOT a phantom — it's a legitimate downstream change.

```python
def is_legitimate_downstream(file: str, scope: IntendedScope, graph: FileGraph) -> bool:
    """A file is legitimate if it's within 2 hops of any in-scope file."""
    for scope_file in scope.target_files:
        if graph.distance(scope_file, file) <= 2:
            return True
        if graph.distance(file, scope_file) <= 2:  # Reverse: file imports scope
            return True
    return False
```

**3b. Smart auto-ignore with categories**

Instead of a flat ignore list, categorize side-effect files:

```python
AUTO_IGNORE_CATEGORIES = {
    "lockfiles": {
        "patterns": ["*.lock", "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock", "Gemfile.lock", "pnpm-lock.yaml"],
        "reason": "Dependency lockfiles auto-update when packages change",
    },
    "generated": {
        "patterns": ["*.min.js", "*.min.css", "*.map", "*.d.ts", "dist/", "build/", "__pycache__/"],
        "detection": "Check for 'auto-generated' or 'do not edit' in first 5 lines",
        "reason": "Auto-generated files change as a side effect of source changes",
    },
    "config_drift": {
        "patterns": [".env.example", "*.sample", "docker-compose.yml"],
        "reason": "Config files often need minor updates alongside feature changes",
        "severity": "info",   # Show but don't count toward risk score
    },
    "migrations": {
        "patterns": ["migrations/", "alembic/versions/", "prisma/migrations/"],
        "reason": "Database migrations are expected side effects of model changes",
        "severity": "info",
    },
}
```

**3c. Learning mode (v0.2 stretch goal)**

Track false positive dismissals over time:

```bash
# Developer dismisses a phantom flag
diff-guard dismiss src/redis_cache.py --related-to auth

# This writes to .diff-guard-learned.yml
# Next time, redis_cache.py won't be flagged when scope involves auth
```

**3d. Confidence display**

Always show HOW confident the tool is in its assessment. Developers trust tools that acknowledge uncertainty:

```
⚠️  Phantom changes (2 files):
   src/auth/session.py         +18 / -9    [confidence: 72%]
   │  → Not mentioned in scope, but 1 hop from login.py via imports
   │  → Might be intentional — review recommended
   │
   src/middleware/rate_limit.py +6 / -6     [confidence: 94%]
   │  → 0 import-chain connection to any in-scope file
   │  → Completely unrelated to "fix login form validation"
   │  → LIKELY UNINTENDED
```

---

## Amendment 4: Test suggester as standalone value

### Problem identified
> "Ship the test suggester as a standalone win. Even if phantom detection needs tuning, the test mapper is immediately valuable."

### Resolution: Make `diff-guard test` a first-class command

**New command:**

```bash
# Just tell me which tests to run for my staged changes
$ diff-guard test

🧪 Tests affected by your changes:

  src/auth/login.py → tests/test_login.py (direct match)
  src/auth/session.py → tests/test_session.py (direct match)
  src/auth/session.py → tests/integration/test_auth_flow.py (imports session)
  src/middleware/rate_limit.py → tests/test_rate_limit.py (direct match)

  Run all: pytest tests/test_login.py tests/test_session.py tests/integration/test_auth_flow.py tests/test_rate_limit.py -v

  Estimated time: ~12s (based on last pytest --durations output)
```

**This command:**
- Has ZERO false positive risk — it's purely mapping changes to tests.
- Is useful even without any scope analysis.
- Can be adopted independently of the full blast radius analysis.
- Serves as the entry point for adoption: install diff-guard for the test mapper, stay for the blast radius.

**Add to pre-commit hook options:**

```yaml
# .diff-guard.yml
hook:
  mode: "test-only"   # Only suggest tests, don't do blast radius analysis
  # OR
  mode: "full"        # Full blast radius + test suggestion (default)
  # OR
  mode: "check-only"  # Blast radius only, no test suggestion
```

**Updated implementation priority:** Move `test_mapper.py` and the `diff-guard test` command into the v0.1 must-have list, implemented immediately after `diff_parser.py` and BEFORE the phantom change detector.

---

## Amendment 5: Updated implementation priorities

### v0.1 (weekend) — reordered based on critique

Build in this exact order. Each step is independently useful.

| Step | Module | Why this order |
|------|--------|---------------|
| 1 | `diff_parser.py` | Foundation — everything else depends on this |
| 2 | `python_analyzer.py` | AST-based, stdlib only, most common language |
| 3 | `file_graph.py` | Build import graph from Python AST analyzer |
| 4 | `test_mapper.py` | **Standalone win** — immediately useful, zero false positive risk |
| 5 | `cli.py` with `diff-guard test` | Ship the test suggester as the first usable command |
| 6 | `scope_analyzer.py` | Priority 1 (prompt file) + Priority 3 (commit message) ONLY |
| 7 | `phantom_change_detector.py` | With import-chain whitelisting from Amendment 3 |
| 8 | `blast_radius.py` | Downstream impact using file_graph |
| 9 | `regression_risk_scorer.py` | Composite scoring |
| 10 | `terminal_reporter.py` | Pretty output with confidence display |
| 11 | `cli.py` with `diff-guard check` | Full analysis command |
| 12 | `pre_commit.py` + `install` command | Git hook |
| 13 | `generic_analyzer.py` | Grep-based fallback for non-Python |
| 14 | Tests, README, pyproject.toml | Ship it |

### v0.2 (week after)

| Priority | Module | Notes |
|----------|--------|-------|
| 1 | `tree_sitter_js_analyzer.py` | JS/TS with proper aliased path + barrel file support |
| 2 | `.diff-guard.yml` config | Project area mapping (solves the redis_cache problem) |
| 3 | `json_reporter.py` + `markdown_reporter.py` | Machine-readable output |
| 4 | Scope inference (Priority 4) | Heuristic fallback — build LAST, tune carefully |
| 5 | `diff-guard dismiss` learning | Track false positive dismissals |
| 6 | `github_reporter.py` | Post to PRs |
| 7 | Go/Rust/Java tree-sitter analyzers | Expand language coverage |
| 8 | `diff-guard graph` visualization | Nice-to-have |

---

## Amendment 6: Additional design principles (from critique)

Add these to the original spec's "Design principles" section:

9. **Test suggester is the trojan horse.** The `diff-guard test` command is the adoption wedge. It provides immediate, risk-free value (no false positives possible) and gets the tool installed. Once installed, developers discover the blast radius features. Every piece of marketing, README, and demo should lead with the test suggester.

10. **Confidence is a first-class signal.** Every phantom change flag MUST include a confidence percentage and a one-line explanation of WHY it was flagged. "This file has no import-chain connection to any file in your stated scope" is actionable. "This file seems unrelated" is not.

11. **The JS/TS ecosystem is hostile to regex.** Never claim JS/TS support without tree-sitter. If tree-sitter is not installed and a JS/TS project is detected, show a clear warning and degrade to generic (grep-based) analysis. Do NOT silently run regex-based import parsing that will produce wrong results on aliased paths, barrel files, or dynamic imports.

12. **Scope confidence gates everything.** If scope confidence is below 0.4 (inferred from diff only), the tool should NEVER exit with a non-zero code. It can suggest, but it cannot block. Only explicit scope (prompt file, CLI arg) should be allowed to gate commits.

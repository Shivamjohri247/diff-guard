#!/usr/bin/env bash
# basic_usage.sh - diff-guard basic CLI usage examples
#
# Run these commands from the root of your git repository.

set -euo pipefail

echo "=== diff-guard Basic Usage ==="
echo ""

# 1. Initialize a config file with defaults
echo "1. Create default config:"
echo "   $ diff-guard init"
echo ""

# 2. Check staged changes (default)
echo "2. Check staged changes:"
echo "   $ git add src/app.py tests/test_app.py"
echo "   $ diff-guard check"
echo ""

# 3. Check with explicit scope
echo "3. Check with explicit scope description:"
echo "   $ diff-guard check --scope 'add user authentication'"
echo ""

# 4. Check last commit
echo "4. Review the last commit:"
echo "   $ diff-guard check --last-commit"
echo ""

# 5. Check diff against a branch
echo "5. Check diff against a branch:"
echo "   $ diff-guard check --diff main"
echo ""

# 6. Get JSON output
echo "6. JSON output for scripts:"
echo "   $ diff-guard check --json"
echo ""

# 7. Fail on specific risk level
echo "7. Fail if risk reaches 'review' level:"
echo "   $ diff-guard check --fail-on review"
echo ""

# 8. Suggest tests
echo "8. Suggest tests for staged changes:"
echo "   $ diff-guard test"
echo ""

# 9. Get the test command only
echo "9. Get just the test command:"
echo "   $ diff-guard test --command-only"
echo ""

# 10. Markdown report
echo "10. Markdown report for PR comments:"
echo "    $ diff-guard check --markdown"
echo ""

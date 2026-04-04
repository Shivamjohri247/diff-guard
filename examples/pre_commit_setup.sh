#!/usr/bin/env bash
# pre_commit_setup.sh - Set up diff-guard as a git pre-commit hook
#
# This script shows how to install and configure diff-guard
# to run automatically before every commit.

set -euo pipefail

echo "=== diff-guard Pre-commit Hook Setup ==="
echo ""

# 1. Install the hook (uses default settings)
echo "1. Install with defaults (fail on 'danger'):"
echo "   $ diff-guard install"
echo "   # Output: Installed diff-guard as pre-commit hook in .git/hooks/pre-commit"
echo ""

# 2. Install with custom fail threshold
echo "2. Install with stricter threshold (fail on 'review'):"
echo "   $ diff-guard install --fail-on review"
echo ""

# 3. Install in test-only mode
echo "3. Install in test-only mode:"
echo "   $ diff-guard install --mode test-only"
echo ""

# 4. Configure behavior in .diff-guard.yml
echo "4. Configure hook behavior in .diff-guard.yml:"
cat <<'EOF'
   hook:
     fail_on: "danger"     # safe | review | danger | never
     auto_test: false      # automatically run suggested tests
     show_report: true     # show full report in hook output
     mode: "full"          # test-only | full | check-only
EOF
echo ""
echo ""

# 5. Skip the hook when needed
echo "5. Skip the hook (use sparingly):"
echo "   $ git commit --no-verify -m 'emergency fix'"
echo ""

# 6. Uninstall the hook
echo "6. Uninstall the hook:"
echo "   $ diff-guard install --uninstall"
echo ""

# 7. Verify hook is installed
echo "7. Check if hook is active:"
echo "   $ cat .git/hooks/pre-commit"
echo "   # Look for 'diff-guard' markers"
echo ""

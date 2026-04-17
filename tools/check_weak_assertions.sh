#!/usr/bin/env bash
# Scan test files for weak assertion patterns that are likely tautological.
# Exit 1 if any violations found, 0 if clean.

set -euo pipefail

TARGET="${1:-trajeval/tests}"
VIOLATIONS=0

echo "Scanning $TARGET for weak assertions..."

# Pattern 1: assert ... or True (always passes)
if grep -rn 'assert.*or True' "$TARGET" 2>/dev/null; then
    echo "^^^ VIOLATION: 'assert ... or True' is always True"
    VIOLATIONS=$((VIOLATIONS + 1))
fi

# Pattern 2: assert ... or False (the 'or False' is meaningless but not dangerous)
if grep -rn 'assert.*or False' "$TARGET" 2>/dev/null; then
    echo "^^^ WARNING: 'assert ... or False' — the 'or False' is a no-op"
fi

# Pattern 3: assert X or Y where Y is likely always true
# This catches the pattern from the review: assert A != B or len(C) == len(D)
DISJUNCTIVE=$(grep -rn 'assert .* or ' "$TARGET" 2>/dev/null || true)
if [ -n "$DISJUNCTIVE" ]; then
    echo ""
    echo "=== Disjunctive assertions (assert X or Y) — review manually ==="
    echo "$DISJUNCTIVE"
    echo ""
    echo "For each match, ask: if X is False and Y is True, should the test pass?"
    echo "If not, split into two separate asserts."
    VIOLATIONS=$((VIOLATIONS + 1))
fi

if [ "$VIOLATIONS" -gt 0 ]; then
    echo ""
    echo "FAILED: $VIOLATIONS weak assertion pattern(s) found"
    exit 1
else
    echo "OK: no weak assertion patterns found"
    exit 0
fi

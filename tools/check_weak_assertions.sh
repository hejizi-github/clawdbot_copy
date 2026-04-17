#!/usr/bin/env bash
# Scan test files for weak assertion patterns.
# Exit 1 if dangerous patterns found (or True / or False).
# Exit 0 but print warnings for assert...or patterns that need manual review.

set -euo pipefail

TESTS_DIR="${1:-trajeval/tests}"
EXIT_CODE=0
WARNINGS=0

if [ ! -d "$TESTS_DIR" ]; then
    echo "ERROR: Tests directory '$TESTS_DIR' not found"
    exit 1
fi

echo "=== Checking for weak assertions in $TESTS_DIR ==="
echo

# Pattern 1: CRITICAL — "or True" / "or False" makes assertions no-ops
echo "--- Pattern 1: assert ... or True/False (always vacuous) ---"
HITS=$(grep -rn "assert.*or True\b\|assert.*or False\b" "$TESTS_DIR" 2>/dev/null || true)
if [ -n "$HITS" ]; then
    echo "FAIL: Found vacuous assertions:"
    echo "$HITS"
    EXIT_CODE=1
else
    echo "OK: No vacuous assertions found."
fi
echo

# Pattern 2: WARNING — "assert X or Y" needs manual review
echo "--- Pattern 2: assert ... or ... (review for tautologies) ---"
HITS=$(grep -rn "assert.*\bor\b" "$TESTS_DIR" 2>/dev/null || true)
if [ -n "$HITS" ]; then
    COUNT=$(echo "$HITS" | wc -l | tr -d ' ')
    echo "REVIEW: $COUNT assertion(s) with 'or' — verify each is intentional:"
    echo "$HITS"
    echo
    echo "For each: if the right side is almost always True, the left side is never tested."
    WARNINGS=$COUNT
else
    echo "OK: No disjunctive assertions found."
fi
echo

if [ $EXIT_CODE -ne 0 ]; then
    echo "RESULT: FAIL — found dangerous patterns that must be fixed."
elif [ $WARNINGS -gt 0 ]; then
    echo "RESULT: WARN — $WARNINGS pattern(s) need manual review."
else
    echo "RESULT: PASS — no weak assertion patterns detected."
fi

exit $EXIT_CODE

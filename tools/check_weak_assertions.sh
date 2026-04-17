#!/usr/bin/env bash
# Scan test files for weak assertion patterns.
# Exit 1 only for CRITICAL patterns (always-true/always-false).
# WARNINGs are printed for review but don't block.
#
# Usage: bash tools/check_weak_assertions.sh [test_dir]
#   --strict   also exit 1 on WARNING patterns

set -euo pipefail

TEST_DIR="${1:-tests/}"
STRICT=0
for arg in "$@"; do
    [ "$arg" = "--strict" ] && STRICT=1
done

CRITICAL=0
WARNINGS=0

echo "Scanning $TEST_DIR for weak assertion patterns..."
echo

# CRITICAL: or True / or False — always logic errors
HITS=$(grep -rn 'assert.*\bor True\b\|assert.*\bor False\b' "$TEST_DIR" 2>/dev/null || true)
if [ -n "$HITS" ]; then
    echo "=== CRITICAL: 'or True' / 'or False' in assertions (always passes/fails) ==="
    echo "$HITS"
    echo
    CRITICAL=$((CRITICAL + $(echo "$HITS" | wc -l | tr -d ' ')))
fi

# WARNING: assert X or Y — review for tautologies
HITS=$(grep -rn 'assert.*\bor\b' "$TEST_DIR" 2>/dev/null | grep -v '\bor True\b\|or False\b' || true)
if [ -n "$HITS" ]; then
    echo "=== WARNING: 'assert ... or ...' patterns (review for tautologies) ==="
    echo "$HITS"
    echo
    echo "  Verify each: would the test fail if the behavior changed completely?"
    echo
    WARNINGS=$((WARNINGS + $(echo "$HITS" | wc -l | tr -d ' ')))
fi

echo "Result: $CRITICAL critical, $WARNINGS warnings."

if [ "$CRITICAL" -gt 0 ]; then
    exit 1
fi
if [ "$STRICT" -eq 1 ] && [ "$WARNINGS" -gt 0 ]; then
    exit 1
fi
exit 0

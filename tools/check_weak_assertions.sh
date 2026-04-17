#!/usr/bin/env bash
# Scan test files for weak assertion patterns.
# Exit 1 for CRITICAL patterns (always-true/always-false).
# WARNINGs are printed for review but don't block unless --strict.
# Add '# weak-assert-ok' to suppress false positives.
#
# Usage: bash tools/check_weak_assertions.sh [test_dir] [--strict]

set -euo pipefail

TEST_DIR="${1:-trajeval/tests}"
STRICT=0
for arg in "$@"; do
    [ "$arg" = "--strict" ] && STRICT=1
done

if [ ! -d "$TEST_DIR" ]; then
    echo "Tests directory not found: $TEST_DIR"
    exit 2
fi

CRITICAL=0
WARNINGS=0

echo "Scanning $TEST_DIR for weak assertion patterns..."
echo

# CRITICAL: or True / or False — always logic errors
HITS=$(grep -rn 'assert.*\bor True\b\|assert.*\bor False\b' "$TEST_DIR" --include='*.py' 2>/dev/null | grep -v '# weak-assert-ok' || true)
if [ -n "$HITS" ]; then
    echo "=== CRITICAL: 'or True' / 'or False' in assertions (always passes/fails) ==="
    echo "$HITS"
    echo
    CRITICAL=$((CRITICAL + $(echo "$HITS" | wc -l | tr -d ' ')))
fi

# WARNING: assert X or Y — review for tautologies
HITS=$(grep -rn 'assert.*\bor\b' "$TEST_DIR" --include='*.py' 2>/dev/null | grep -v '\bor True\b\|or False\b' | grep -v '# weak-assert-ok' || true)
if [ -n "$HITS" ]; then
    echo "=== WARNING: 'assert ... or ...' patterns (review for tautologies) ==="
    echo "$HITS"
    echo
    echo "  Verify each: would the test fail if the behavior changed completely?"
    echo "  To suppress: add '# weak-assert-ok' comment to the line."
    echo
    WARNINGS=$((WARNINGS + $(echo "$HITS" | wc -l | tr -d ' ')))
fi

# WARNING: if-guarded assertions (assert inside if — silently skipped)
HITS=$(grep -rn -A1 '^\s*if\b' "$TEST_DIR" --include='*.py' 2>/dev/null | grep -B1 'assert\b' | grep -v '# weak-assert-ok' || true)
if [ -n "$HITS" ]; then
    echo "=== WARNING: If-guarded assertions (may be silently skipped) ==="
    echo "$HITS"
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

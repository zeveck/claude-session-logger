#!/bin/bash
# Run all claude-session-logger tests.
#
# Usage:
#   ./tests/run_tests.sh              # run all tests (py + js)
#   ./tests/run_tests.sh --py-only    # python only
#   ./tests/run_tests.sh --js-only    # node only
#   ./tests/run_tests.sh -v           # verbose

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PKG_DIR"

PASS_ARGS="$*"
FAILED=0

echo "================================"
echo "claude-session-logger test suite"
echo "================================"
echo

# --- Converter tests ---
echo "--- Converter tests ---"
if python3 tests/test_converter.py $PASS_ARGS; then
    echo "  PASS"
else
    echo "  FAIL"
    FAILED=1
fi
echo

# --- Hook tests ---
echo "--- Hook tests ---"
if python3 tests/test_hooks.py $PASS_ARGS; then
    echo "  PASS"
else
    echo "  FAIL"
    FAILED=1
fi
echo

# --- Installer tests ---
echo "--- Installer tests ---"
if python3 tests/test_installer.py $PASS_ARGS; then
    echo "  PASS"
else
    echo "  FAIL"
    FAILED=1
fi
echo

# --- Summary ---
if [ $FAILED -eq 0 ]; then
    echo "All tests passed."
else
    echo "Some tests FAILED."
    exit 1
fi

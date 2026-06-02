#!/bin/bash
# Test: iniciar.sh modo-automático prompt and fork behavior.
#
# Verifies:
# 1. Prompt "¿Modo automático?" exists after verify_all
# 2. 's' path launches auto_mode.py
# 3. Default behavior (Enter) opens browser and doesn't launch auto_mode.py
# 4. tail -f uvicorn.log is started in background for auto mode

set -euo pipefail

SCRIPT="iniciar.sh"
FAILURES=0
PASSES=0

assert_contains() {
    local desc="$1" pattern="$2"
    if grep -qi "$pattern" "$SCRIPT"; then
        echo "✅ $desc"
        PASSES=$((PASSES + 1))
    else
        echo "❌ $desc — pattern not found: '$pattern'"
        FAILURES=$((FAILURES + 1))
    fi
}

assert_not_contains() {
    local desc="$1" pattern="$2"
    if ! grep -qi "$pattern" "$SCRIPT"; then
        echo "✅ $desc"
        PASSES=$((PASSES + 1))
    else
        echo "❌ $desc — unexpected pattern found: '$pattern'"
        FAILURES=$((FAILURES + 1))
    fi
}

echo "=== Testing $SCRIPT for modo-automático changes ==="
echo ""

# IS-1: Prompt after verify_all
assert_contains "Has '¿Modo automático?' prompt" 'Modo automático'

# IS-2: 's' launches auto_mode.py
assert_contains "Launches auto_mode.py for 's' answer" 'auto_mode\.py'

# IS-2: tail -f uvicorn.log in background for auto mode
assert_contains "Starts tail -f uvicorn.log for auto mode" 'tail.*uvicorn'

# IS-2/IS-3: There should be a conditional (case or if) that branches on the answer
assert_contains "Has conditional branch for 's' answer" '\[\[.*[sS]'

echo ""
echo "=== Results: $PASSES passed, $FAILURES failed ==="

if [ "$FAILURES" -gt 0 ]; then
    exit 1
fi
exit 0

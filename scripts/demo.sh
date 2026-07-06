#!/usr/bin/env bash
# Proofloop §3 acceptance demo — idempotent (fresh mktemp workdir each run).
#
#   1. Guard blocks the unready deploy (exit 2, command never spawned).
#   2. Fix: point config at prod, set env vars, run tests through proofloop.
#      (Config is fixed BEFORE running tests so the test stamp binds to the
#       final worktree — editing code after tests would re-arm tests_not_run.)
#   3. Guard passes; the stand-in deploy executes (exit 0); the passing
#      record auto-resolves the blocked one.
#   4. Recurrence: STRIPE_API_KEY unset again → blocked instantly WITH a
#      recalled_from citation of the first record.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v proofloop >/dev/null 2>&1; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi
command -v proofloop >/dev/null 2>&1 || { echo "proofloop not on PATH (pip install -e 'cli[dev]' into .venv first)"; exit 1; }

# Deterministic, offline demo: never call a real LLM.
export PROOFLOOP_NO_LLM=1

WORK="$(mktemp -d "${TMPDIR:-/tmp}/proofloop-demo.XXXXXX")"
APP="$WORK/app"
cp -R "$ROOT/demo-app" "$APP"
cd "$APP"
echo "demo workdir: $WORK"

banner() { printf '\n════════ %s ════════\n' "$*"; }
fail()   { echo "ASSERTION FAILED: $*" >&2; exit 1; }

# rec <index> <python-expression over record dict r> — reads memory.jsonl
rec() {
  python3 - "$1" "$2" <<'PY'
import json, sys
records = [json.loads(l) for l in open(".proofloop/memory.jsonl") if l.strip()]
r = records[int(sys.argv[1])]
print(json.dumps(eval(sys.argv[2], {"r": r})))
PY
}
record_count() {
  python3 -c 'import sys; print(sum(1 for l in open(".proofloop/memory.jsonl") if l.strip()))'
}

# ---------------------------------------------------------------------------
banner "STEP 1 — deploy through the gate with nothing ready → BLOCKED"
echo "\$ proofloop guard deploy -- ./deploy.sh"
rc=0
env -u STRIPE_API_KEY -u DATABASE_URL proofloop guard deploy -- ./deploy.sh \
  >"$WORK/step1.out" 2>&1 || rc=$?
cat "$WORK/step1.out"
[ "$rc" -eq 2 ] || fail "step 1: expected exit 2 (BLOCKED), got $rc"
if grep -q "Deployed (stand-in)" "$WORK/step1.out"; then
  fail "step 1: deploy command ran despite the block"
fi
[ "$(record_count)" -eq 1 ] || fail "step 1: expected exactly 1 memory record"
[ "$(rec 0 'r["gate_passed"]')" = "false" ] || fail "step 1: record must be gate_passed=false"
RID1="$(rec 0 'r["id"]' | tr -d '"')"
echo "→ blocked as expected (exit 2), record $RID1 written, deploy never ran ✔"

# ---------------------------------------------------------------------------
banner "STEP 2 — apply the fixes the gate listed"
echo "\$ <edit config.py: localhost → https://api.example.com, DEBUG → False>"
python3 - <<'PY'
from pathlib import Path
p = Path("config.py")
s = p.read_text()
s = s.replace("http://localhost:8000", "https://api.example.com")
s = s.replace("DEBUG = True", "DEBUG = False")
p.write_text(s)
PY
export STRIPE_API_KEY=sk_test_demo123
export DATABASE_URL=postgres://demo
echo "\$ export STRIPE_API_KEY=... DATABASE_URL=..."
echo "\$ proofloop run tests -- python3 -m pytest -q"
proofloop run tests -- python3 -m pytest -q

# ---------------------------------------------------------------------------
banner "STEP 3 — deploy again → GATE PASSES, stand-in deploy executes"
echo "\$ proofloop guard deploy -- ./deploy.sh"
rc=0
proofloop guard deploy -- ./deploy.sh >"$WORK/step3.out" 2>&1 || rc=$?
cat "$WORK/step3.out"
[ "$rc" -eq 0 ] || fail "step 3: expected exit 0, got $rc"
grep -q "Deployed (stand-in)" "$WORK/step3.out" || fail "step 3: stand-in deploy did not run"
[ "$(record_count)" -eq 2 ] || fail "step 3: expected 2 memory records"
[ "$(rec 1 'r["gate_passed"]')" = "true" ] || fail "step 3: record must be gate_passed=true"
[ "$(rec 1 'r["resolves"]' | tr -d '"')" = "$RID1" ] || fail "step 3: passing record must resolve $RID1"
[ "$(rec 0 'r["resolution"]["status"]' | tr -d '"')" = "auto_resolved" ] \
  || fail "step 3: $RID1 must be auto_resolved"
echo "→ gate passed, deploy executed, record chk_002 resolves $RID1 ✔"

# ---------------------------------------------------------------------------
banner "STEP 4 — recurrence: STRIPE_API_KEY lost again → BLOCKED + RECALLED"
echo "\$ proofloop guard deploy -- ./deploy.sh   (STRIPE_API_KEY unset)"
rc=0
env -u STRIPE_API_KEY proofloop guard deploy -- ./deploy.sh \
  >"$WORK/step4.out" 2>&1 || rc=$?
cat "$WORK/step4.out"
[ "$rc" -eq 2 ] || fail "step 4: expected exit 2 (BLOCKED), got $rc"
if grep -q "Deployed (stand-in)" "$WORK/step4.out"; then
  fail "step 4: deploy command ran despite the block"
fi
[ "$(rec 2 'r["recalled_from"]' | tr -d '"')" = "$RID1" ] \
  || fail "step 4: new record must cite recalled_from=$RID1"
echo "→ recurrence caught instantly, cites $RID1 via recalled_from ✔"

# ---------------------------------------------------------------------------
banner "DEMO PASSED"
echo "DEMO PASSED"

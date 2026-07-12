#!/usr/bin/env bash
# Proofjury §3 acceptance demo — idempotent (fresh mktemp workdir each run).
#
#   1. Guard blocks the unready deploy (exit 2, command never spawned) —
#      ALL SIX advertised failure classes fire.
#   2. Fix: point config at prod, remove the hardcoded secret, set env vars,
#      run tests/build/lint through proofjury.
#      (ALL file edits happen BEFORE the proofjury run stamps — any edit
#       after stamping re-arms stale_digest and step 3 would block.)
#   3. Guard passes; the stand-in deploy executes (exit 0); the passing
#      record auto-resolves the blocked one.
#   4. Recurrence: STRIPE_API_KEY unset again → blocked WITH a
#      recalled_from citation of the first record.
#   5. LLM leg: fresh workdir + mock OpenRouter server → the judge writes
#      the diagnosis, the ledger records the cost. The exit code is 2 with
#      or without the LLM — deterministic checks decide, the LLM explains.
#      The fresh repo also recalls the app repo's prior block cross-repo
#      (recalled_from = app:chk_NNN) via the user-level store registry.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v proofjury >/dev/null 2>&1; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi
command -v proofjury >/dev/null 2>&1 || { echo "proofjury not on PATH (pip install -e 'cli[dev]' into .venv first)"; exit 1; }

# Deterministic, offline demo: steps 1-4 never call a real LLM. Step 5
# un-sets this for its own guard call (its "network" is a 127.0.0.1 mock).
export PROOFJURY_NO_LLM=1

WORK="$(mktemp -d "${TMPDIR:-/tmp}/proofjury-demo.XXXXXX")"
# Isolated config home for the WHOLE demo: gates register their store in a
# user-level registry (cross-repo memory recall) and step 5 runs `login` —
# neither may ever touch the developer's real ~/.config/proofjury.
export XDG_CONFIG_HOME="$WORK/xdg"
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
records = [json.loads(l) for l in open(".proofjury/memory.jsonl") if l.strip()]
r = records[int(sys.argv[1])]
print(json.dumps(eval(sys.argv[2], {"r": r})))
PY
}
record_count() {
  python3 -c 'import sys; print(sum(1 for l in open(".proofjury/memory.jsonl") if l.strip()))'
}

# ---------------------------------------------------------------------------
banner "STEP 1 — deploy through the gate with nothing ready → BLOCKED"
echo "\$ proofjury guard deploy -- ./deploy.sh"
rc=0
env -u STRIPE_API_KEY -u DATABASE_URL -u WEBHOOK_SIGNING_SECRET \
  proofjury guard deploy -- ./deploy.sh \
  >"$WORK/step1.out" 2>&1 || rc=$?
cat "$WORK/step1.out"
[ "$rc" -eq 2 ] || fail "step 1: expected exit 2 (BLOCKED), got $rc"
if grep -q "Deployed (stand-in)" "$WORK/step1.out"; then
  fail "step 1: deploy command ran despite the block"
fi
[ "$(record_count)" -eq 1 ] || fail "step 1: expected exactly 1 memory record"
[ "$(rec 0 'r["gate_passed"]')" = "false" ] || fail "step 1: record must be gate_passed=false"
# All six advertised failure classes fire in one story:
CLASSES="$(rec 0 'sorted({c["failure_class"] for c in r["checks"] if not c["passed"]})')"
[ "$CLASSES" = '["build_failure", "config_mismatch", "hardcoded_secret", "missing_env_var", "preprod_check_skipped", "tests_not_run"]' ] \
  || fail "step 1: expected all six failure classes, got $CLASSES"
FAILED_CHECKS="$(rec 0 'sorted(c["name"] for c in r["checks"] if not c["passed"])')"
[ "$FAILED_CHECKS" = '["build", "config", "env_vars", "preprod", "secrets", "tests"]' ] \
  || fail "step 1: expected all six checks failed, got $FAILED_CHECKS"
RID1="$(rec 0 'r["id"]' | tr -d '"')"
echo "→ blocked as expected (exit 2), all six failure classes fired, record $RID1 written, deploy never ran ✔"

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
echo "\$ <edit notifications.py: hardcoded secret → os.environ read>"
python3 - <<'PY'
from pathlib import Path
Path("notifications.py").write_text(
    '"""Webhook notifications (demo fixture)."""\n'
    "\n"
    "import os\n"
    "\n"
    'WEBHOOK_SIGNING_SECRET = os.environ["WEBHOOK_SIGNING_SECRET"]\n'
    "\n"
    "\n"
    "def sign(payload: bytes) -> str:\n"
    "    import hashlib\n"
    "    import hmac\n"
    "\n"
    "    return hmac.new(WEBHOOK_SIGNING_SECRET.encode(), payload, hashlib.sha256).hexdigest()\n"
)
PY
export STRIPE_API_KEY=sk_test_demo123
export DATABASE_URL=postgres://demo
export WEBHOOK_SIGNING_SECRET=1c2d3e4f5a6b7089  # ≥8 chars → scrub coverage applies
echo "\$ export STRIPE_API_KEY=... DATABASE_URL=... WEBHOOK_SIGNING_SECRET=..."
# Stamps come LAST — after every file edit — or stale_digest re-arms.
echo "\$ proofjury run tests -- python3 -m pytest -q"
proofjury run tests -- python3 -m pytest -q
echo "\$ proofjury run build -- python3 -m compileall -q ."
proofjury run build -- python3 -m compileall -q .
echo "\$ proofjury run lint -- python3 -m compileall -q app.py"
proofjury run lint -- python3 -m compileall -q app.py

# ---------------------------------------------------------------------------
banner "STEP 3 — deploy again → GATE PASSES, stand-in deploy executes"
echo "\$ proofjury guard deploy -- ./deploy.sh"
rc=0
proofjury guard deploy -- ./deploy.sh >"$WORK/step3.out" 2>&1 || rc=$?
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
echo "\$ proofjury guard deploy -- ./deploy.sh   (STRIPE_API_KEY unset)"
rc=0
env -u STRIPE_API_KEY proofjury guard deploy -- ./deploy.sh \
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
banner "STEP 5 — LLM judge leg (mock OpenRouter, isolated config)"
APP2="$WORK/app-llm"
cp -R "$ROOT/demo-app" "$APP2"   # fresh copy: no priors → no recall short-circuit
cd "$APP2"
python3 "$ROOT/scripts/mock_openrouter.py" >"$WORK/mock.port" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for _ in $(seq 50); do [ -s "$WORK/mock.port" ] && break; sleep 0.1; done
[ -s "$WORK/mock.port" ] || fail "step 5: mock server never reported a port"
PORT="$(cat "$WORK/mock.port")"
echo "\$ proofjury login --provider openrouter --api-key demo-key --no-verify"
proofjury login --provider openrouter --api-key demo-key --no-verify
echo "\$ proofjury guard deploy -- ./deploy.sh   (LLM judge via mock server)"
rc=0
env -u PROOFJURY_NO_LLM -u STRIPE_API_KEY -u DATABASE_URL -u WEBHOOK_SIGNING_SECRET \
  PROOFJURY_OPENROUTER_URL="http://127.0.0.1:$PORT/chat/completions" \
  proofjury guard deploy -- ./deploy.sh >"$WORK/step5.out" 2>&1 || rc=$?
cat "$WORK/step5.out"
[ "$rc" -eq 2 ] || fail "step 5: expected exit 2 (BLOCKED with or without LLM), got $rc"
[ "$(rec 0 'r["judge_model_id"]' | tr -d '"')" = "openai/gpt-4o-mini" ] \
  || fail "step 5: judge_model_id must be the mock LLM's, got $(rec 0 'r["judge_model_id"]')"
python3 - <<'PY' || fail "step 5: ledger cost"
import json
entries = [json.loads(l) for l in open(".proofjury/ledger.jsonl") if l.strip()]
assert len(entries) == 1 and entries[0]["cost_usd"] == 0.00042, entries
PY
# Cross-repo memory recall: app-llm has no priors of its own, but the same
# failure was blocked in the app repo earlier in this demo — the record
# must cite it as <repo_id>:<chk_id>. Foreign priors never short-circuit
# the judge, which is why the mock LLM assertion above still held.
RECALLED5="$(rec 0 'r["recalled_from"]' | tr -d '"')"
case "$RECALLED5" in
  app:chk_*) ;;
  *) fail "step 5: expected cross-repo recalled_from app:chk_NNN, got '$RECALLED5'" ;;
esac
echo "→ LLM judge explained the block via the mock server, cost hit the ledger,"
echo "  and the failure was recalled cross-repo from $RECALLED5 ✔"

# ---------------------------------------------------------------------------
banner "DEMO PASSED"
echo "DEMO PASSED"

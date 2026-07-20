#!/usr/bin/env bash
# Seed the local dashboard from a fresh demo.sh run — gives the dashboard
# blocked/passed/recalled/cross-repo/LLM-judged data to render.
#
# Prereqs: dashboard docker compose up, `npm run dev` running in dashboard/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ running the demo (this exercises the full gate)…"
DEMO_OUT="$("$REPO_ROOT/scripts/demo.sh" 2>&1)" || {
  echo "$DEMO_OUT" | tail -20
  echo "demo.sh failed — cannot seed"
  exit 1
}
echo "$DEMO_OUT" | grep -q "DEMO PASSED" || { echo "demo did not pass"; exit 1; }

WORKDIR="$(echo "$DEMO_OUT" | grep -o 'demo workdir: [^ ]*' | head -1 | cut -d' ' -f3)"
if [ -z "$WORKDIR" ]; then
  echo "could not locate the demo workdir in demo.sh output"
  exit 1
fi
echo "→ demo workdir: $WORKDIR"

cd "$REPO_ROOT/dashboard"
for app in app app-llm; do
  store="$WORKDIR/$app/.proofjury"
  if [ -d "$store" ]; then
    echo "→ seeding $app"
    npm run --silent seed -- "$store" --repo-name "demo-$app"
  fi
done
echo "✓ seeded — open http://localhost:3000 and use the dev login"

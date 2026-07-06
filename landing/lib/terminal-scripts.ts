// REAL transcripts — transcribed from an actual `proofloop guard` run of the
// §3 acceptance scenario (scripts/demo.sh, proofloop 0.1.0, deterministic
// judge, fully offline). The rich panel chrome is dropped (the Terminal
// component draws its own window); evidence, diagnosis, fix steps, and record
// footers are verbatim CLI output. Secret values in typed commands are masked.

export type TerminalLine = {
  /** cmd = typed character-by-character with "$ " prefix; out = fades in; status = verdict pop */
  type: "cmd" | "out" | "status";
  text: string;
  tone?: "red" | "green" | "dim" | "amber";
  /** extra pause (ms) before this line appears */
  delayMs?: number;
};

/**
 * The full block → fix → allow story, played in the Interception section.
 * Verbatim from run chk_001 → chk_002 of the acceptance demo.
 */
export const gateStoryScript: TerminalLine[] = [
  { type: "cmd", text: "proofloop guard deploy -- ./deploy.sh" },
  { type: "status", text: "⛔ DEPLOY BLOCKED — proofloop", tone: "red", delayMs: 500 },
  { type: "out", text: "env_vars  missing_env_var  DATABASE_URL (db.py:3), STRIPE_API_KEY (payments.py:14) unset", tone: "red", delayMs: 350 },
  { type: "out", text: "tests     tests_not_run    no test run recorded for this worktree", tone: "red" },
  { type: "out", text: "config    config_mismatch  API_BASE_URL points at localhost (config.py:3), debug mode is enabled (config.py:4)", tone: "red" },
  {
    type: "out",
    text: "Blocking deploy — DATABASE_URL, STRIPE_API_KEY referenced (db.py:3, payments.py:14) but unset; the first request will crash. Tests have not run against this worktree. Config is not production-ready.",
    tone: "amber",
    delayMs: 500,
  },
  { type: "out", text: "Fix:", delayMs: 300 },
  { type: "out", text: "  1. Set the missing env vars: export DATABASE_URL=<value>; export STRIPE_API_KEY=<value>" },
  { type: "out", text: "  2. Run: proofloop run tests -- pytest" },
  { type: "out", text: "  3. Point config at production values; disable debug flags" },
  { type: "out", text: "record chk_001 → .proofloop/memory.jsonl · proof: .proofloop/runs/chk_001/ · exit 2", tone: "dim", delayMs: 300 },
  // — the agent applies the listed fixes —
  { type: "cmd", text: "export STRIPE_API_KEY=••••• DATABASE_URL=•••••", delayMs: 900 },
  { type: "cmd", text: "proofloop run tests -- pytest -q", delayMs: 300 },
  { type: "out", text: "4 passed in 0.01s", tone: "green", delayMs: 450 },
  { type: "out", text: "proofloop: recorded tests run (exit 0) → .proofloop/runs/", tone: "dim" },
  // — re-run the gate —
  { type: "cmd", text: "proofloop guard deploy -- ./deploy.sh", delayMs: 500 },
  { type: "status", text: "✅ GATE PASSED — executing: ./deploy.sh", tone: "green", delayMs: 450 },
  { type: "out", text: "All 4 checks passed (2 skipped: build, preprod).", tone: "green", delayMs: 300 },
  { type: "out", text: "✦ Resolves chk_001 — the failure diagnosed there is now fixed.", tone: "amber" },
  { type: "out", text: "→ Releasing to production...", tone: "dim", delayMs: 400 },
  { type: "out", text: "✅ Deployed", tone: "green", delayMs: 300 },
];

/**
 * The recurrence catch, played in the Memory section.
 * Verbatim from run chk_003 of the acceptance demo: the same class of
 * mistake recurs later, and the gate cites the prior diagnosed record.
 */
export const recurrenceScript: TerminalLine[] = [
  { type: "cmd", text: "proofloop guard deploy -- ./deploy.sh" },
  { type: "status", text: "⛔ DEPLOY BLOCKED — proofloop", tone: "red", delayMs: 450 },
  { type: "out", text: "env_vars  missing_env_var  STRIPE_API_KEY (payments.py:14) unset", tone: "red", delayMs: 300 },
  {
    type: "out",
    text: "Seen before — matches chk_001: same STRIPE_API_KEY failure. Blocking deploy — STRIPE_API_KEY referenced (payments.py:14) but unset; the first request will crash.",
    tone: "amber",
    delayMs: 400,
  },
  { type: "out", text: "↩ Recalled from chk_001 — this failure was diagnosed before in this repo.", tone: "amber", delayMs: 350 },
  { type: "out", text: "record chk_003 → .proofloop/memory.jsonl · proof: .proofloop/runs/chk_003/ · exit 2", tone: "dim", delayMs: 300 },
];

// All restaged landing copy and record data. The narrative claims here are
// competitively vetted (see landing/PRODUCT.md) — the only exclusivity claim
// allowed is "no one guards correctness at the deploy moment", and the CLI
// evidence mirrors the real acceptance-demo transcripts in
// lib/terminal-scripts.ts (the content source of record).

export const COMMAND = "proofjury guard deploy -- ./deploy.sh";

export const HERO = {
  title: "The last command before production.",
  sub: "Proofjury is the correctness gate for AI-written code. It catches what your agent got wrong before it ships, proves why, and remembers.",
  hint: "scroll — the deploy is already moving",
};

export type JourneyFragment = {
  text: string;
  kind: "big" | "small" | "thesis";
};

export const JOURNEY: JourneyFragment[] = [
  { text: "Your agent wrote it.", kind: "big" },
  { text: "Reviewed it.", kind: "big" },
  { text: "And is about to ship it.", kind: "big" },
  { text: "No engineer has read the diff.", kind: "small" },
  { text: "Guardrails watch for dangerous commands.", kind: "small" },
  { text: "Test suites check whatever got run.", kind: "small" },
  { text: "No one guards correctness at the deploy moment.", kind: "thesis" },
];

export type Exhibit = {
  tag: string;
  title: string;
  body: string;
  evidence: string;
};

export const EXHIBITS: Exhibit[] = [
  {
    tag: "Exhibit A",
    title: "The missing key",
    body: "Referenced in the code. Set nowhere. The first request crashes.",
    evidence: "payments.py:14 · STRIPE_API_KEY unset",
  },
  {
    tag: "Exhibit B",
    title: "The localhost config",
    body: "Works on the agent's machine. Ships to yours.",
    evidence: "config.py:3 · API_BASE_URL=localhost:8000",
  },
  {
    tag: "Exhibit C",
    title: "The skipped tests",
    body: "Marked done. Never proven.",
    evidence: "pytest · 0 runs this session",
  },
];

export type GateCheck = {
  name: string;
  verdict: string;
  pass: boolean;
};

// The four checks of run chk_001, as staged in the S4 ledger.
export const GATE_CHECKS: GateCheck[] = [
  { name: "env_vars", verdict: "missing_env_var", pass: false },
  { name: "tests", verdict: "tests_not_run", pass: false },
  { name: "config", verdict: "config_mismatch", pass: false },
  { name: "secrets", verdict: "clean", pass: true },
];

export const RECORD_LINE =
  "record chk_001 → .proofjury/memory.jsonl · proof: .proofjury/runs/chk_001/ · exit 2";

export type ReceiptRow = {
  name: string;
  verdict: string;
  fail: boolean;
  loc: string;
  detail: string;
};

// Mirrors the real chk_001 record from the acceptance demo.
export const RECEIPT_ROWS: ReceiptRow[] = [
  { name: "env_vars", verdict: "✗ missing_env_var", fail: true, loc: "db.py:3", detail: "DATABASE_URL unset" },
  { name: "env_vars", verdict: "✗ missing_env_var", fail: true, loc: "payments.py:14", detail: "STRIPE_API_KEY unset" },
  { name: "tests", verdict: "✗ tests_not_run", fail: true, loc: "session.json", detail: "no run for this worktree" },
  { name: "config", verdict: "✗ config_mismatch", fail: true, loc: "config.py:3", detail: "API_BASE_URL → localhost" },
  { name: "config", verdict: "✗ config_mismatch", fail: true, loc: "config.py:4", detail: "DEBUG = True" },
  { name: "secrets", verdict: "✓ clean", fail: false, loc: "—", detail: "passed · 0 findings" },
];

export type TranscriptLine = {
  kind: "cmd" | "out" | "status";
  text: string;
  tone?: "red" | "green" | "amber" | "dim";
};

// Condensed from gateStoryScript (chk_001 → chk_002): the deny payload is
// applied, tests actually run, and the same gate passes.
export const FIX_TRANSCRIPT: TranscriptLine[] = [
  { kind: "cmd", text: "export STRIPE_API_KEY=••••• DATABASE_URL=•••••" },
  { kind: "cmd", text: "proofjury run tests -- pytest -q" },
  { kind: "out", text: "4 passed in 0.01s", tone: "green" },
  { kind: "cmd", text: "proofjury guard deploy -- ./deploy.sh" },
  { kind: "status", text: "✅ GATE PASSED — executing: ./deploy.sh", tone: "green" },
  { kind: "out", text: "✦ Resolves chk_001 — the failure diagnosed there is now fixed.", tone: "amber" },
];

export type MemoryRecord = {
  id: string;
  cls: string;
  status: string;
  tone: "red" | "green" | "amber";
  newest?: boolean;
};

// chk_001/002/003 mirror the acceptance demo; chk_014/027 are later runs.
export const MEMORY_RECORDS: MemoryRecord[] = [
  { id: "chk_001", cls: "missing_env_var", status: "diagnosed", tone: "red" },
  { id: "chk_002", cls: "gate_passed", status: "resolves chk_001", tone: "green" },
  { id: "chk_014", cls: "config_mismatch", status: "diagnosed", tone: "red" },
  { id: "chk_027", cls: "hardcoded_secret", status: "diagnosed", tone: "red" },
  { id: "chk_003", cls: "missing_env_var", status: "recalled · 64 ms", tone: "amber", newest: true },
];

export const RECALL_QUOTE =
  "Seen before — matches chk_001: same STRIPE_API_KEY failure.";

// Install block (S8). Until the PyPI release lands, the git+https line is
// primary; flip `lines` to ["uv tool install proofjury", "proofjury init"]
// after the v0.1.0 publish.
export const INSTALL = {
  heading: "Two commands. Any repo.",
  lines: [
    'pip install "git+https://github.com/kevincui1034/proofjury.git#subdirectory=cli"',
    "proofjury init",
  ],
  note: "Python 3.11+ · runs fully offline · Apache-2.0",
};

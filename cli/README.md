# Proofloop

**A correctness gate for AI-written code.** Coding agents now write large
volumes of code that no human reviews. Proofloop catches what an agent got
*wrong* before it ships, **proves** exactly why with `file:line` evidence,
and **remembers** each failure so it's caught faster next time — across any
agent: Claude, Codex, Cursor.

```
proofloop guard deploy -- ./deploy.sh
```

If the deterministic readiness checks fail, the command is **never spawned**.
You get a proof-backed explanation, exact fix steps, a training-ready JSONL
record, and — on recurrence — an instant citation of the prior diagnosis
(`recalled_from`).

## Install

```bash
# from GitHub (Python 3.11+)
pip install "git+https://github.com/kevincui1034/proofloop.git#subdirectory=cli"

# or, working in a clone:
pip install -e 'cli[dev]'        # includes the test extras

proofloop init                   # wire up .proofloop/, agent hooks, config
```

Requires Python 3.11+. Runtime deps: typer, rich, httpx.

## The gate in 30 seconds

```bash
# 1. Gate a deploy — checks fail → BLOCKED (exit 2), command never runs
proofloop guard deploy -- ./deploy.sh

# 2. Fix, and tell the gate tests actually ran against this worktree
export STRIPE_API_KEY=... DATABASE_URL=...
proofloop run tests -- pytest -q

# 3. Gate passes → the deploy executes, exit code propagates
proofloop guard deploy -- ./deploy.sh
```

## Commands

| Command | What it does |
| --- | --- |
| `proofloop guard <action> -- <cmd...>` | Run readiness checks; exec `<cmd>` only if they pass. `--force` (logged), `--no-exec`, `--json`. |
| `proofloop run <kind> -- <cmd...>` | Run tests/build/lint/typecheck and stamp a worktree-bound session marker. |
| `proofloop resolve <id> --status accepted\|false_positive` | Label whether a block was correct. |
| `proofloop confirm <id> --outcome shipped\|rolled_back` | Post-deploy ground truth. |
| `proofloop memory list` / `show <id>` | Inspect the memory. |
| `proofloop init` | Create `.proofloop/`, write the Claude Code PreToolUse hook, `.proofloop.toml`, print the AGENTS.md snippet. |

### Exit codes

- `0` — gate passed and the child succeeded (or `--no-exec`)
- `N` — the child's exit code (`127`/`126` when the child command is missing/not executable; `128 + N` when the child dies to signal `N`)
- `2` — **BLOCKED** (the command was never spawned)
- `3` — internal proofloop error (an internal error never silently allows)
- `64` — usage error (`EX_USAGE`) — e.g. the wrapped command was not separated with ` -- `

## Checks (deterministic — no LLM in the pass/fail path)

| Check | Failure class |
| --- | --- |
| env vars referenced in code vs. deploy env | `missing_env_var` |
| tests ran & passed against *this* worktree | `tests_not_run` / `test_failure` |
| build ran & passed | `build_failure` |
| lint/typecheck ran & passed | `preprod_check_skipped` |
| no hardcoded secrets (patterns + entropy) | `hardcoded_secret` |
| config sanity (localhost, debug, test keys) | `config_mismatch` |

See [TAXONOMY.md](TAXONOMY.md) for the open failure-class spec.

## The judge (offline-first)

Failures are *explained* — never decided — by a judge. By default this is a
deterministic template engine (`deterministic/proofloop-v1`, zero cost,
offline). Set `OPENROUTER_API_KEY` to route explanations through a cheap LLM
via OpenRouter (model: `PROOFLOOP_JUDGE_MODEL`, default `openai/gpt-4o-mini`;
per-call cost is appended to `.proofloop/ledger.jsonl`). Set
`PROOFLOOP_NO_LLM=1` to force offline. Any LLM error falls back to the
deterministic judge. On a strong recurrence (same failure-class set and
shared evidence with a recalled record) the prior diagnosis is cited
deterministically — **no model call**, even when a key is set.

## Memory — the dataset is the product

Every run (pass or fail) appends one training-ready record to
`.proofloop/memory.jsonl` (+ a human section in `memory.md`): the checks,
evidence, judge input/output, proof refs, `recalled_from`, and a
`resolution` filled in later by `resolve`/`confirm` or automatically when a
passing run fixes a prior block (`resolves` / `auto_resolved`). Env var
**values** of 8+ characters are scrubbed from all persisted output (records,
proof files, run logs); shorter values are not scrubbed — they collide with
ordinary text. Ambient non-credential vars (`PWD`, `HOME`, `PATH`, `LC_*`,
etc.) are exempt so paths stay readable in proof records.

## Agent integration

`proofloop init` installs a Claude Code `PreToolUse` hook that intercepts
deploy-shaped shell commands (configurable in `.proofloop.toml [hook]`). A
failing gate answers with a **deny** whose reason contains the failed checks,
evidence, and exact fix steps — so the agent self-corrects. Everything else
(non-deploy commands, passing gates) gets **no decision**, leaving Claude
Code's normal permission flow untouched — the hook never auto-approves. For
all agents, add the snippet from [AGENTS.md](AGENTS.md) to your repo.

## License

Apache-2.0.

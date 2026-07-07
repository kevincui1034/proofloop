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
| `proofloop login` / `logout` | Store / remove an LLM API key for judge explanations (BYOK). |
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
offline). Pass/fail never depends on a model: deterministic checks decide, the
LLM only writes the explanation, any LLM error falls back to the deterministic
judge, and the gate runs fully offline with no key. On a strong recurrence
(same failure-class set and shared evidence with a recalled record) the prior
diagnosis is cited deterministically — **no model call**, even when a key is set.

### LLM explanations (optional, BYOK)

To get LLM-written explanations, bring your own key — no file editing:

```bash
proofloop login          # pick a provider, paste a key (hidden input)
proofloop logout         # remove it
# scriptable:  proofloop login --provider anthropic --api-key <key> --no-verify
```

`login` stores the key at `~/.config/proofloop/config.toml` (mode `0600`,
outside the repo — one key across all your projects) and does a best-effort
live check. Pick any provider; the defaults are deliberately cheap because the
judge only explains a deterministic finding:

| Provider | Default model | Cost tier |
| --- | --- | --- |
| OpenRouter (default) | `openai/gpt-4o-mini` | cheap |
| Anthropic | `claude-haiku-4-5` | cheapest Claude |
| OpenAI | `gpt-4o-mini` | cheap |

All three adapters call the provider's REST endpoint directly over `httpx` —
no vendor SDK. Per-call cost is appended to `.proofloop/ledger.jsonl`.

Env vars still work and take precedence over the stored config:
`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` select and key a
provider (auto-detected in that order); `PROOFLOOP_JUDGE_PROVIDER` names one
explicitly; `PROOFLOOP_JUDGE_MODEL` overrides the model; `PROOFLOOP_NO_LLM=1`
forces offline.

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
deploy-shaped shell commands. A failing gate answers with a **deny** whose
reason contains the failed checks, evidence, and exact fix steps — so the
agent self-corrects. Everything else (non-deploy commands, passing gates) gets
**no decision**, leaving Claude Code's normal permission flow untouched — the
hook never auto-approves. For all agents, add the snippet from
[AGENTS.md](AGENTS.md) to your repo.

### What counts as a "deploy"

Out of the box the hook recognizes the common deploy surfaces — Vercel,
Netlify, Fly, Railway, Cloudflare (`wrangler`), Heroku (`git push heroku`),
AWS (`sam`/`cdk deploy`, `cloudformation deploy`), GCP (`gcloud run/app/functions deploy`),
Kubernetes (`kubectl apply`, `helm upgrade`), Docker (`docker push`),
Terraform/Pulumi (`apply`/`up`), Serverless/SST, Kamal, Capistrano,
`npm/pnpm/yarn/bun run deploy`, `make deploy`, and `./deploy.sh`. Patterns are
anchored to the command position, so a tool name inside a quoted string or a
file argument (`cat wrangler.toml`, `git commit -m "add docker push"`) is not
mistaken for a deploy.

Tune it in `.proofloop.toml [hook]`:

```toml
[hook]
# ADD to the built-ins (recommended — keeps every default):
deploy_patterns_extra = ['(?:^|[;&|])\s*bin/release\b']

# REPLACE them entirely (advanced — you own the whole list):
# deploy_patterns = ['^make ship$']
```

`proofloop init` also **detects your stack** — it reads deploy markers
(`fly.toml`, `wrangler.toml`, `Dockerfile`, `serverless.yml`, `*.tf`, …) to
print what it found, and seeds `deploy_patterns_extra` from `package.json`
deploy scripts the defaults might miss (e.g. `deploy:prod`).

## License

Apache-2.0.

# Proofjury

**The last command before production.**

Coding agents write code no human reviews — and then they ship it. Proofjury is the correctness gate for AI-written code: it intercepts the deploy command itself, decides with deterministic checks, explains exactly why with evidence, and remembers every diagnosed failure so recurrence is caught instantly.

```
$ proofjury guard deploy -- ./deploy.sh

⛔ DEPLOY BLOCKED — proofjury

  env_vars   missing_env_var   DATABASE_URL (db.py:3), STRIPE_API_KEY
                               (payments.py:14) unset
  tests      tests_not_run     no test run recorded for this worktree
  config     config_mismatch   API_BASE_URL points at localhost (config.py:3),
                               debug mode is enabled (config.py:4)

  Blocking deploy — DATABASE_URL, STRIPE_API_KEY referenced (db.py:3,
  payments.py:14) but unset; the first request will crash. Tests have not
  run against this worktree. Config is not production-ready.

  Fix:
    1. Set the missing env vars: export DATABASE_URL=<value>; export
       STRIPE_API_KEY=<value>
    2. Run: proofjury run tests -- pytest
    3. Point config at production values; disable debug flags

record chk_001 → .proofjury/memory.jsonl · proof: .proofjury/runs/chk_001/ · exit 2
```

The deploy command was never spawned. After the fixes, the gate passes and the
record resolves `chk_001`; when the same mistake recurs, the block cites the
prior diagnosis: `↩ Recalled from chk_001`.

## Why this exists

- **The gate cannot be talked past.** Deterministic checks decide pass/fail; the LLM only explains. An agent can't argue its way through an unset env var.
- **Blocks the deploy — then tells your agent exactly how to fix it.** A Proofjury denial is structured feedback the agent consumes to fix the failure and re-run. The gate makes your agent finish the job.
- **Every deploy ships with a proof record.** Reproducible evidence — which check failed, `file:line`, command output — not a regenerated opinion.
- **It remembers.** Every diagnosed failure is stored in training-ready form; recurrence is caught instantly and cites the prior record.
- **Doesn't care which agent wrote it.** Claude Code, Codex, Cursor — same gate, same checks, same memory. Correctness, not security: your guardrails stop the dangerous command; Proofjury stops the broken one.

## Layout

| Path | What it is |
|---|---|
| [`cli/`](cli/) | The `proofjury` CLI (Python 3.11+, Apache-2.0): `guard`, `run`, `resolve`, `confirm`, `memory`, `init`, `status` |
| [`demo-app/`](demo-app/) | An intentionally-broken agent-built app — the acceptance-test bed |
| [`scripts/demo.sh`](scripts/demo.sh) | End-to-end demo: block → fix → allow → recurrence caught from memory |
| [`landing/`](landing/) | proofjury.com landing page (Next.js, static export) |
| [`dashboard/`](dashboard/) | app.proofjury.com hosted dashboard (Next.js + Supabase Postgres/Drizzle + Auth.js + Cloudflare R2): every gate run as a trace — verdict, evidence, blast radius, judge advice feed |

## Quick start

```bash
# install (Python 3.11+) — PyPI release imminent:
uv tool install proofjury            # or: pipx install proofjury
# until then, straight from GitHub:
pip install "git+https://github.com/kevincui1034/proofjury.git#subdirectory=cli"

cd your-project
proofjury init                       # wires agent hooks + AGENTS.md gate instructions
proofjury run tests -- pytest        # stamp a test run (first deploy blocks without one)
proofjury guard deploy -- vercel --prod
```

Install user-wide (`uv tool install` / `pipx`) rather than into a project venv: GUI-launched agents don't inherit a shell-activated venv PATH, and the hook command has to resolve for them. `proofjury status` shows gate readiness — setup, hooks, PATH, run stamps — anytime. For local development, clone and `pip install -e cli`.

Optionally, `proofjury connect` links a machine to your hosted dashboard (device-code flow, token at `~/.config/proofjury/config.toml`, mode `0600`): after that every gate run best-effort syncs its already-scrubbed record — sync never blocks, slows, or fails the gate, and `PROOFJURY_NO_SYNC=1` or `proofjury disconnect` turns it off. Analysis stays local; the cloud only stores and visualizes.

Runs fully offline with no key. For LLM-written explanations, `proofjury login` picks a provider — OpenRouter, Anthropic, or OpenAI — and stores the key at `~/.config/proofjury/config.toml` (mode `0600`, outside the repo). Env vars still work and take precedence: `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, plus `PROOFJURY_JUDGE_PROVIDER` and `PROOFJURY_JUDGE_MODEL`. Defaults are cheap per provider (OpenRouter `openai/gpt-4o-mini`, Anthropic `claude-haiku-4-5`, OpenAI `gpt-4o-mini`). The LLM only writes the explanation — deterministic checks still decide pass/fail.

## Docs

- [`proofjury-full-scope.md`](proofjury-full-scope.md) — full venture scope
- [`cli/TAXONOMY.md`](cli/TAXONOMY.md) — the deploy-time correctness failure taxonomy (open spec)

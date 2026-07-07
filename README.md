# Proofloop

**The last command before production.**

Coding agents write code no human reviews — and then they ship it. Proofloop is the correctness gate for AI-written code: it intercepts the deploy command itself, decides with deterministic checks, explains exactly why with evidence, and remembers every diagnosed failure so recurrence is caught instantly.

```
$ proofloop guard deploy -- ./deploy.sh

⛔ DEPLOY BLOCKED — proofloop

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
    2. Run: proofloop run tests -- pytest
    3. Point config at production values; disable debug flags

record chk_001 → .proofloop/memory.jsonl · proof: .proofloop/runs/chk_001/ · exit 2
```

The deploy command was never spawned. After the fixes, the gate passes and the
record resolves `chk_001`; when the same mistake recurs, the block cites the
prior diagnosis: `↩ Recalled from chk_001`.

## Why this exists

- **The gate cannot be talked past.** Deterministic checks decide pass/fail; the LLM only explains. An agent can't argue its way through an unset env var.
- **Blocks the deploy — then tells your agent exactly how to fix it.** A Proofloop denial is structured feedback the agent consumes to fix the failure and re-run. The gate makes your agent finish the job.
- **Every deploy ships with a proof record.** Reproducible evidence — which check failed, `file:line`, command output — not a regenerated opinion.
- **It remembers.** Every diagnosed failure is stored in training-ready form; recurrence is caught instantly and cites the prior record.
- **Doesn't care which agent wrote it.** Claude Code, Codex, Cursor — same gate, same checks, same memory. Correctness, not security: your guardrails stop the dangerous command; Proofloop stops the broken one.

## Layout

| Path | What it is |
|---|---|
| [`cli/`](cli/) | The `proofloop` CLI (Python 3.11+, Apache-2.0): `guard`, `run`, `resolve`, `confirm`, `memory`, `init` |
| [`demo-app/`](demo-app/) | An intentionally-broken agent-built app — the acceptance-test bed |
| [`scripts/demo.sh`](scripts/demo.sh) | End-to-end demo: block → fix → allow → recurrence caught from memory |
| [`landing/`](landing/) | proofloop.dev landing page (Next.js, static export) |

## Quick start

```bash
# install (Python 3.11+)
pip install "git+https://github.com/kevincui1034/proofloop.git#subdirectory=cli"

cd your-project
proofloop init                       # writes agent hooks; prints AGENTS.md snippet
proofloop guard deploy -- vercel --prod
```

`pipx install "git+https://github.com/kevincui1034/proofloop.git#subdirectory=cli"` works too (isolated). Or clone and `pip install -e cli` for local development.

Runs fully offline with no key. For LLM-written explanations, `proofloop login` picks a provider — OpenRouter, Anthropic, or OpenAI — and stores the key at `~/.config/proofloop/config.toml` (mode `0600`, outside the repo). Env vars still work and take precedence: `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, plus `PROOFLOOP_JUDGE_PROVIDER` and `PROOFLOOP_JUDGE_MODEL`. Defaults are cheap per provider (OpenRouter `openai/gpt-4o-mini`, Anthropic `claude-haiku-4-5`, OpenAI `gpt-4o-mini`). The LLM only writes the explanation — deterministic checks still decide pass/fail.

## Docs

- [`proofloop-claude-code-handoff-final.md`](proofloop-claude-code-handoff-final.md) — MVP build brief
- [`proofloop-full-scope.md`](proofloop-full-scope.md) — full venture scope
- [`cli/TAXONOMY.md`](cli/TAXONOMY.md) — the deploy-time correctness failure taxonomy (open spec)

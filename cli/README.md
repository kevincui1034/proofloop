# Proofjury

**A correctness gate for AI-written code.** Coding agents now write large
volumes of code that no human reviews. Proofjury catches what an agent got
*wrong* before it ships, **proves** exactly why with `file:line` evidence,
and **remembers** each failure so it's caught faster next time — across any
agent: Claude, Codex, Cursor.

```
proofjury guard deploy -- ./deploy.sh
```

If the deterministic readiness checks fail, the command is **never spawned**.
You get a proof-backed explanation, exact fix steps, a training-ready JSONL
record, and — on recurrence — an instant citation of the prior diagnosis
(`recalled_from`).

## Install

```bash
# from GitHub (Python 3.11+)
pip install "git+https://github.com/kevincui1034/proofjury.git#subdirectory=cli"

# or, working in a clone:
pip install -e 'cli[dev]'        # includes the test extras

proofjury init                   # wire up .proofjury/, agent hooks, config
```

Requires Python 3.11+. Runtime deps: typer, rich, httpx.

## The gate in 30 seconds

```bash
# 1. Gate a deploy — checks fail → BLOCKED (exit 2), command never runs
proofjury guard deploy -- ./deploy.sh

# 2. Fix, and tell the gate tests actually ran against this worktree
export STRIPE_API_KEY=... DATABASE_URL=...
proofjury run tests -- pytest -q

# 3. Gate passes → the deploy executes, exit code propagates
proofjury guard deploy -- ./deploy.sh
```

## Commands

| Command | What it does |
| --- | --- |
| `proofjury guard <action> -- <cmd...>` | Run readiness checks; exec `<cmd>` only if they pass. `--force` (logged), `--no-exec`, `--json`, `--env-file` (evaluate env checks against the deploy target's env file instead of your shell). |
| `proofjury run <kind> -- <cmd...>` | Run tests/build/lint/typecheck and stamp a worktree-bound session marker. |
| `proofjury resolve <id> --status accepted\|false_positive` | Label whether a block was correct. |
| `proofjury confirm <id> --outcome shipped\|rolled_back` | Post-deploy ground truth. |
| `proofjury advisory approve\|reject\|confirm <id#i>` | Review an advisory finding (e.g. `chk_012#0`): approve a held one for delivery, reject a wrong one (it never re-fires; a delivered one is retracted on the next event), confirm a correct one. |
| `proofjury login` / `logout` | Store / remove an LLM API key for judge explanations (BYOK). |
| `proofjury memory list` / `show <id>` | Inspect the memory. |
| `proofjury memory export` | Emit the records as training-ready JSONL (each row gets a computed `label`). `--labeled-only`, `--failure-class X`, `--dedupe`, `-o PATH`. |
| `proofjury memory stats` | Dataset health metrics + judge spend from the cost ledger. `--json`. |
| `proofjury init` | Create `.proofjury/`, write the Claude Code PreToolUse hook, `.proofjury.toml`, print the AGENTS.md snippet. |

### Exit codes

- `0` — gate passed and the child succeeded (or `--no-exec`)
- `N` — the child's exit code (`127`/`126` when the child command is missing/not executable; `128 + N` when the child dies to signal `N`)
- `2` — **BLOCKED** (the command was never spawned)
- `3` — internal proofjury error (an internal error never silently allows)
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
| schema changed without a migration (Prisma/Django; others via config) | `pending_migration` |
| manifest changed without its lockfile | `lockfile_drift` |
| TODO/FIXME/NotImplementedError in newly added lines | `unfinished_work` |

See [TAXONOMY.md](TAXONOMY.md) for the open failure-class spec.

## The judge (offline-first)

Failures are *explained* — never decided — by a judge. By default this is a
deterministic template engine (`deterministic/proofjury-v1`, zero cost,
offline). Pass/fail never depends on a model: deterministic checks decide, the
LLM only writes the explanation, any LLM error falls back to the deterministic
judge, and the gate runs fully offline with no key. On a strong recurrence
(same failure-class set and shared evidence with a recalled record) the prior
diagnosis is cited deterministically — **no model call**, even when a key is set.

### LLM explanations (optional, BYOK)

To get LLM-written explanations, bring your own key — no file editing:

```bash
proofjury login          # pick a provider, paste a key (hidden input)
proofjury logout         # remove it
# scriptable:  proofjury login --provider anthropic --api-key <key> --no-verify
```

`login` stores the key at `~/.config/proofjury/config.toml` (mode `0600`,
outside the repo — one key across all your projects) and does a best-effort
live check. Pick any provider; the defaults are deliberately cheap because the
judge only explains a deterministic finding:

| Provider | Default model | Cost tier |
| --- | --- | --- |
| OpenRouter (default) | `openai/gpt-4o-mini` | cheap |
| Anthropic | `claude-haiku-4-5` | cheapest Claude |
| OpenAI | `gpt-4o-mini` | cheap |

All three adapters call the provider's REST endpoint directly over `httpx` —
no vendor SDK. Per-call cost is appended to `.proofjury/ledger.jsonl`.

Env vars still work and take precedence over the stored config:
`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` select and key a
provider (auto-detected in that order); `PROOFJURY_JUDGE_PROVIDER` names one
explicitly; `PROOFJURY_JUDGE_MODEL` overrides the model; `PROOFJURY_NO_LLM=1`
forces offline.

### The advisory judge (optional — model judgment, never blocking)

With an LLM configured, the gate also runs one **advisory** review of the
change at the deploy boundary: risks the deterministic checklist structurally
can't enumerate (missing error handling around an external call, a change
that doesn't match what the agent was asked to do) plus notes on existing
deterministic failures ("likely a false positive — the same shape was labeled
`false_positive` in `chk_042`"). Findings are grounded in the repo's memory
of past outcomes and each records the prior ids it cited (`grounded_in`).

Two surfaces, one authority: **advisory findings never change the decision.**
The exit code is identical with zero findings or ten; offline the record is
byte-identical to today. The judge is skipped for trivial diffs and when the
same inputs were already reviewed (`inputs_hash`), and any error or timeout
yields zero findings.

Delivery is confidence-gated: a finding at or above
`auto_inject_min_confidence` (default 0.7) reaches the coding agent this
event as non-blocking context (Claude Code `additionalContext` — no
permission decision is ever attached; on a blocked run it rides along in the
deny reason). Between `hold_min_confidence` (default 0.4) and that, it is
**held**: you see it in the terminal with an `approve`/`reject` command and
the agent only sees it after `proofjury advisory approve chk_012#0` (it goes
out on the next deploy event). Below the floor it is recorded only. You see
every finding either way.

`proofjury advisory reject chk_012#0` does three things: labels the finding
(training signal), permanently stops that finding's signature from re-firing
or grounding future reviews, and — if the agent already saw it — sends a
retraction note on the next deploy event. What an agent already read cannot
be unread; the suppression is immediate, the retraction lands one event
later.

`proofjury advisory confirm` is the graduation path: a signature confirmed
three times shows up in `memory stats` as a **candidate deterministic
check** — the model discovers the class, a human writes the `file:line`
check, and enforcement moves back to the provable core. New failure classes
stay deterministic, never model judgment (see TAXONOMY.md).

Tier-5 findings ("not what was asked") need the task: it's captured
opportunistically from the agent transcript by the hook, or via
`proofjury guard deploy --task "..."`, `PROOFJURY_TASK`, or
`[session].task` in `.proofjury.toml`. Without one they simply don't fire.

Tune or disable in `.proofjury.toml`:

```toml
[advisory]
# enabled = true
# auto_inject_min_confidence = 0.7
# hold_min_confidence = 0.4
# max_findings = 5
# diff_min_lines = 1
# tiers = [4, 5]        # [4] mutes tier-5 findings
# model = ""            # blank → the judge's resolved model
```

## Memory — the dataset is the product

Every run (pass or fail) appends one training-ready record to
`.proofjury/memory.jsonl` (+ a human section in `memory.md`): the checks,
evidence, judge input/output, proof refs, `recalled_from`, and a
`resolution` filled in later by `resolve`/`confirm` or automatically when a
passing run fixes a prior block (`resolves` / `auto_resolved`). Env var
**values** of 8+ characters are scrubbed from all persisted output (records,
proof files, run logs); shorter values are not scrubbed — they collide with
ordinary text. Ambient non-credential vars (`PWD`, `HOME`, `PATH`, `LC_*`,
etc.) are exempt so paths stay readable in proof records.

Labels feed straight back into recall: a record you mark
`--status false_positive` is never recalled again — it stops showing up in
`recalled_from` and stops short-circuiting the judge on recurrences. Every
other label (`accepted`, `overridden`, `auto_resolved`, `confirmed:*`) stays
recallable, because those were correct blocks and "this exact failure was
seen before" is the point of the memory.

Labels also weight recall at the class level: a failure class whose
`false_positive` labels outnumber its `accepted` ones (with at least two)
is treated as noisy, and its priors sort below trusted-class priors —
demoted, never excluded. `accepted` labels rehabilitate a class. The
per-class counts behind this are visible in `memory stats` under
`class_reliability`.

### Memory recall across your repos

Memory compounds across the repos on your machine. Every gate run
registers its repo's store in a user-level registry
(`${XDG_CONFIG_HOME:-~/.config}/proofjury/registry.json`), and when a
failure has no matching prior in the current repo — or as extra context
for the judge — recall also consults your other repos' stores, read-only.
A cross-repo prior is cited as `<repo>:<chk_id>` ("seen before in
\<repo\>") and is context only: it sorts below every same-repo prior,
never short-circuits the judge the way a same-repo recurrence does, and
never affects pass/fail. `proofjury memory repos` shows what recall can
see. Opt a repo out with:

```toml
[memory]
cross_repo = false   # neither reads other repos' stores nor is read by them
```

(or set `PROOFJURY_NO_CROSS_REPO=1` for a single run). Records are
already env-value-scrubbed when written, and nothing ever leaves your
machine — the registry is a local file of local paths.

Two read-only views over the dataset:

```bash
proofjury memory export --labeled-only --dedupe > dataset.jsonl
proofjury memory stats --json
```

`export` emits one JSON row per record with a computed `label`
(`unlabeled`, `accepted`, `false_positive`, `overridden`, `auto_resolved`,
`confirmed:shipped`, `confirmed:rolled_back`); `--dedupe` keeps the last
record per `inputs_hash`. `stats` reports block/pass counts, failure-class
and label distributions, recall hit rate, auto-resolve rate, gate latency,
and judge spend aggregated from `.proofjury/ledger.jsonl`. Both work fully
offline and never modify the store.

## Agent integration

`proofjury init` installs pre-execution hooks that intercept deploy-shaped
shell commands. A failing gate answers with a **deny** whose reason contains
the failed checks, evidence, and exact fix steps — so the agent
self-corrects. Everything else (non-deploy commands, passing gates) gets
**no decision**, leaving the agent's normal permission flow untouched — the
hook never auto-approves. For all agents, add the snippet from
[AGENTS.md](AGENTS.md) to your repo.

### Hook wiring per agent

| Agent | Hook | Wired by init |
| --- | --- | --- |
| Claude Code | `PreToolUse` (matcher `Bash`) | `.claude/settings.json` — always |
| Cursor | `beforeShellExecution` | `.cursor/hooks.json` — when Cursor is detected (or `--all-agents`) |
| OpenAI Codex CLI | `PreToolUse` (matcher `Bash`) | `.codex/hooks.json` — when Codex is detected (or `--all-agents`) |

All three run `proofjury hook` (Cursor/Codex with `--agent cursor|codex`, so
records carry the right `agent_source`). Existing hook entries are merged,
never clobbered, and re-running `init` is idempotent.

Caveats worth knowing:

- **Codex trust:** project-local hooks are inert until you trust the folder —
  run `codex` once and accept the prompt. Codex's streaming exec path can
  bypass hooks, so keep the AGENTS.md snippet for full Codex coverage.
- **Cursor + virtualenvs:** GUI-launched Cursor doesn't inherit a
  shell-activated venv PATH. Install proofjury user-wide (`pipx install
  proofjury`) or put the absolute path in `.cursor/hooks.json`.
- **Cursor exit semantics:** exit 2 blocks; other non-zero exits fail open —
  proofjury's internal-error path therefore denies with exit 2.

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

Tune it in `.proofjury.toml [hook]`:

```toml
[hook]
# ADD to the built-ins (recommended — keeps every default):
deploy_patterns_extra = ['(?:^|[;&|])\s*bin/release\b']

# REPLACE them entirely (advanced — you own the whole list):
# deploy_patterns = ['^make ship$']
```

`proofjury init` also **detects your stack** — it reads deploy markers
(`fly.toml`, `wrangler.toml`, `Dockerfile`, `serverless.yml`, `*.tf`, …) to
print what it found, and seeds `deploy_patterns_extra` from `package.json`
deploy scripts the defaults might miss (e.g. `deploy:prod`).

### Merges and releases

The gate also intercepts two more moments, each with its own patterns
(`release_patterns[_extra]`, `merge_patterns[_extra]` — same convention as
deploy) and its own check profile in `.proofjury.toml [actions]`:

- **Releases** (`npm publish`, `cargo publish`, `twine upload`,
  `gh release create`, `git push --tags` / `git push origin v1.2.3`) are
  gated **by default** — publishing a package is a production-affecting
  moment. Turn off with `[hook] gate_releases = false`. Releases run every
  check, like deploys.
- **Merges** (`git merge <ref>`, `gh pr merge`; never `--abort`/`--continue`)
  are **opt-in** via `[hook] gate_merges = true` — out of the box this would
  block routine merges for anyone not stamping runs. The merge profile
  evaluates code-readiness only (`tests`, `build`, `preprod`); env, secrets,
  and config are deploy-target concerns. Override with
  `[actions.merge] checks = [...]`.

A command matching two groups gates as the strictest story
(deploy > release > merge). Memory recall is action-agnostic: a failure
first diagnosed at deploy time is recalled when the same failure blocks a
release or merge — same repo, same failure class, same fix. You can also
invoke any action directly: `proofjury guard release -- npm publish`.

## License

Apache-2.0.

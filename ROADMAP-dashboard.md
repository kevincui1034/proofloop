# Roadmap: login + hosted dashboard

Status: **built through E3, local-first (2026-07-19)** — Phases B, C, D and
E1–E3 are implemented and verified offline (`dashboard/` app + CLI sync;
458 CLI + 38 dashboard tests). Remaining: the one-time provisioning/deploy
pass (Vercel project, Neon, Blob, GitHub OAuth — see `dashboard/README.md`)
and the E4+ backlog. This document is the source of truth for the
hosted-visibility phases. It extends — never contradicts —
`proofjury-full-scope.md` (§7 open-core split, §10 Phase 2 "teams,
multi-tenant, dashboards, hosted").

## The product in one sentence

After logging in and connecting a repo, a user sees every gate run as a
trace — the verdict, the evidence, the blast radius of the change, the
connected files, and everything the judge has advised their coding agent —
in a visual dashboard the CLI keeps current automatically.

## Architecture principle: their agent computes, we visualize

All analysis happens **locally at gate time** using the user's own machine
and their own BYOK LLM key / coding agent:

- Deterministic checks decide (unchanged, always).
- The deterministic impact analysis (Phase B) runs in the CLI, no LLM.
- Semantic enrichment (advisories, impact summaries) uses the user's
  configured judge — never a server-side model.

The cloud side is **ingest + storage + visualization only**. No server-side
LLM spend, no server-side analysis of user code. Records arrive already
env-value-scrubbed (the ≥8-char scrub applies to everything persisted), and
sync is opt-in: nothing uploads until `proofjury connect`.

## Stack (decided)

- **App**: new `dashboard/` Next.js app in this repo, deployed as its own
  Vercel project at `app.proofjury.com`. `landing/` stays a pure static
  export — its GSAP scroll build is locked and fragile, and a separate app
  preserves the option to move the dashboard to the private repo later
  (open-core split, full-scope §7).
- **DB**: Supabase Postgres + Drizzle ORM (changed from Neon 2026-07-19 by
  owner request). Used as plain Postgres — Auth.js not Supabase Auth, no RLS
  (clients never hit the DB directly). App runtime uses the transaction
  pooler (port 6543); migrations run against the direct/session URL (5432);
  TLS auto-enabled for non-local hosts (`db/index.ts sslConfig`).
  (Portable: Drizzle + `pg` are vendor-neutral, so only the connection
  string + SSL changed — Neon remains a drop-in alternative.)
- **Auth**: Auth.js v5, GitHub OAuth.
- **Proof files**: Cloudflare R2, S3-compatible via `@aws-sdk/client-s3`
  (changed from Vercel Blob 2026-07-19 by owner request). Private bucket —
  a strictly better fit than Vercel Blob's public-by-design URLs: `put()`
  returns no URL and the browser reads proof content only through the authed
  proxy route. Behind the `ProofStorage` interface (`lib/storage.ts`), with
  `LocalDirStorage` for dev/tests; the R2 adapter is verified against MinIO.

---

## Phase B — Blast radius in the CLI (local-first, no cloud dependency)

Deterministic impact analysis at gate time. Valuable immediately in deny
payloads; later it's the dashboard's blast-radius view.

- New `cli/src/proofjury/impact.py`: from `RunContext.changed_files`, build
  a reverse-import graph — Python via `ast`, JS/TS via `import`/`require`
  regex — depth-limited (default 2), repo-relative, no LLM. Output: per
  changed file, its dependents with edge type + depth.
- Persist `runs/chk_NNN/impact.json`; append `"impact.json"` to `proof_refs`
  (additive only — the §5 memory schema key set is pinned by a test).
- Surface top-N impacted files in the deny payload / `additionalContext`:
  "this change touches payments.py, imported by 6 modules including
  checkout".
- **Agent enrichment (opt-in, BYOK)**: feed the impact graph into the
  existing advisory judge input (`judge/advisory.py`) so tier-4/5 findings
  can reason about semantic blast radius. Stored in the existing
  `advisories` array — same firewall rules: any error → zero findings,
  never touches block/exit code.
- Config `[impact]`: `enabled` (default true), `depth`, `max_files`. Skips
  gracefully outside a usable git context (same pattern as the diff-scoped
  checks; the demo stays untouched).

Verification: unit tests for the graph builder (py + ts fixtures); gate
integration test asserting `impact.json` in `proof_refs` and graceful skip
without git; exit-code invariance test (impact never affects the decision).

## Phase C — Cloud foundation: auth, ingest, sync

Dashboard side (`dashboard/`):

- Auth.js GitHub OAuth; `users` table.
- Schema (Drizzle/Neon): `users`, `repos` (CLI `repo_id`, display name,
  owner, optional GitHub link), `records` (extracted columns — id, repo,
  created_at, action, agent_source, gate_passed, failure classes — plus the
  full record as JSONB), `proof_files` (Blob refs), `device_tokens`.
- `POST /api/ingest` — token-authed, idempotent on `(repo_id, record_id)`,
  accepts the record JSON + proof files.
- `POST /api/device` — device-code auth flow for the CLI.

CLI side:

- `proofjury connect` — device-code flow: prints a URL + code, the user
  approves in the browser while logged in, the token lands in
  `~/.config/proofjury/config.toml` (0600, same file as BYOK keys), and the
  repo registers under the account. `proofjury disconnect` reverses it.
- **Auto-sync**: after each gate run, a best-effort background POST of the
  scrubbed record + proof dir. Same firewall discipline as the advisory
  judge — sync can never block, slow, or fail the gate. Unsent record ids
  queue locally and drain on the next run or a manual `proofjury sync`.
- Kill switches: `[sync] enabled = false`, `PROOFJURY_NO_SYNC=1`.

Verification: ingest idempotency tests; CLI sync tests against a mock
endpoint (same pattern as `mock_openrouter.py`); a pinned test that gate
exit codes are identical with sync enabled and the endpoint unreachable.

## Phase D — Dashboard v1 (read-only visualization)

- **Traces list** — every gate run across connected repos: verdict, action
  (deploy/release/merge), agent source, failure classes, time; filter +
  search.
- **Trace detail** — checks with `file:line` evidence, the scrubbed diff,
  recall citations (`recalled_from`, incl. cross-repo `repo:chk_NNN` ids),
  and the **blast radius view**: an interactive graph of changed files →
  dependents from `impact.json`, with the advisory's semantic impact
  summary when present.
- **Judge advice feed** — the chronological answer to "what has the judge
  advised my agent so far": deny payloads (diagnosis + fix steps), injected
  and held advisories with their delivery lifecycle, retractions, and
  whether the advice was followed (`resolves` linkage on the next run).
- **Repo overview** — catches by failure class, gate pass rate over time,
  readiness (mirrors `proofjury status`).

Verification: seed a Neon branch DB from `scripts/demo.sh` output; verify
list/detail/advice-feed render on a Vercel preview deployment.

## Phase E — Interactive + growth (prioritized backlog)

1. **Advisory review from the web** — approve/reject/confirm in the
   dashboard; labels sync down to the CLI on the next gate run (the label +
   retraction machinery already exists).
2. **Graduation board** — the "candidate deterministic checks" queue
   (≥3 confirmed same-signature advisories, already computed in
   `memory/export.py`): one click to accept a candidate into the repo's
   check profile.
3. **Memory / recall explorer** — which priors fire most, class
   reliability, cross-repo recall hits. Makes "it remembers" visible.
4. **Outcome tracking** — `confirmed:shipped` vs `confirmed:rolled_back`
   over time: the honest "did the gate prevent bad deploys" metric, and the
   outcome-label moat axis made visible.
5. **LLM cost view** — chart BYOK judge spend from `ledger.jsonl`.
6. **Shareable proof permalink + README badge** — opt-in public link to a
   single scrubbed trace; "Gated by Proofjury · N catches" badge.
   Distribution loop.
7. **Weekly digest email** — catches, advice given, outcomes.
8. **Teams** — orgs, roles, SSO/RBAC; lives in the private repo per the
   open-core split.

## Copy guardrails (apply to all dashboard/site work)

Never "verification layer", "self-improving loop" / "closing the feedback
loop", or "quality gates". The only exclusivity claim: "no one guards
correctness at the deploy moment" — always paired with "correctness, not
security".

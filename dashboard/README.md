# Proofjury dashboard — app.proofjury.com

Every gate run as a trace: the verdict, the evidence, the blast radius of
the change, and everything the judge has advised your coding agent — kept
current automatically by the CLI.

**Their agent computes, we visualize.** All analysis happens locally at
gate time on the user's machine (deterministic checks decide; BYOK LLM
advises). This app is ingest + storage + visualization only: no
server-side LLM, no server-side analysis of user code. Records arrive
already env-scrubbed, and nothing uploads until `proofjury connect`.

## Local development

```bash
docker compose up -d          # Postgres on :54329
cp .env.example .env.local    # AUTH_DEV_LOGIN=1, BLOB_DRIVER=local
npm install
npm run db:migrate
npm run dev                   # http://localhost:3000 → "Dev login"
```

Seed real data from the acceptance demo (from the repo root, with the dev
server running):

```bash
./scripts/seed-dashboard-demo.sh
```

Or connect a real CLI to the local server:

```bash
PROOFJURY_SYNC_URL=http://localhost:3000/api/v1 proofjury connect
```

## Tests

```bash
npm test        # vitest against a dedicated proofjury_test DB (auto-created)
```

Tests truncate tables between files — they run against `proofjury_test`,
never the dev database. The signature-parity suite asserts the TS port of
`advisory_signature` byte-matches the CLI via the shared fixture
`cli/tests/fixtures/advisory_signatures.json` (its twin is
`cli/tests/test_signature_fixtures.py`).

## Architecture notes

- `db/schema.ts` — Drizzle schema. `records.data` holds the full CLI
  MemoryRecord verbatim (additive, pinned CLI-side); hot columns are
  extracted at ingest. Advisories are per-finding rows (E1 labels them
  individually; E2 groups by signature). `label_events.id` is the CLI's
  down-sync cursor.
- `/api/v1/ingest` — bearer-token, idempotent on (repo, record_id); an
  exact replay is `unchanged`, a changed replay (relabeled locally)
  updates — that's how CLI-side labels flow up. Unknown record keys pass
  through (the schema is additive).
- `/api/v1/device/*` — device-code flow; everything secret stored hashed;
  token minted exactly once.
- Proof files (checks.json / context.json / diff.patch / impact.json) go
  to Cloudflare R2 in production (`LocalDirStorage` in dev). R2 buckets are
  private, so `put()` returns no URL and the browser reads proof content
  only through the authed proxy route `/api/proof/...`. R2 speaks the S3
  API via `@aws-sdk/client-s3`; the same adapter is verified in tests
  against MinIO.
- Web label actions reproduce the CLI semantics exactly (approve requires
  held; reject after delivery stages a retraction). The CLI pulls events
  post-gate, so web advice reaches the agent on its next gate run.

Copy guardrails (all UI copy): never "verification layer",
"self-improving loop" / "closing the feedback loop", or "quality gates".
The only exclusivity claim is "no one guards correctness at the deploy
moment", paired with "correctness, not security".

## Deploy (one-time provisioning)

Separate Vercel project (root directory `dashboard/`) at app.proofjury.com.

- **Postgres — Supabase.** Create a project; set two env vars in Vercel:
  the app runtime `DATABASE_URL` = the **transaction pooler** URL (port
  6543, `…pooler.supabase.com`), and run migrations against the
  **direct/session** URL (port 5432):
  `DATABASE_URL=<direct-url> npm run db:migrate` per schema change. TLS is
  auto-enabled for non-local hosts (override with `DATABASE_SSL` /
  `DATABASE_SSL_CA`). We use Supabase as plain Postgres — Auth.js, not
  Supabase Auth; no RLS (clients never touch the DB directly).
- **Storage — Cloudflare R2.** Create a private bucket + an R2 API token,
  then set `R2_ENDPOINT` (`https://<account_id>.r2.cloudflarestorage.com`),
  `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. Leave
  `BLOB_DRIVER` unset in production. No public access / custom domain
  needed — proof files are served only through the authed proxy.
- **Auth — GitHub OAuth app.** Callback
  `https://app.proofjury.com/api/auth/callback/github`; set
  `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET` / `AUTH_SECRET` / `APP_URL`.

The landing app stays a separate static-export project.

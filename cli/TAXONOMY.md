# Deploy-Time Correctness Failure Taxonomy v0.2

An open specification for the failure classes Proofjury detects at the
deploy boundary. Scope: **correctness, not security** — mistakes an AI
coding agent (or human) makes that break a deployment, not vulnerabilities.

Each class defines: what it is, how it is detected deterministically, the
evidence format persisted with every finding, and an example memory-record
check entry. Evidence is always verifiable against the tree at `file:line`.

Classes are ordered by severity as used by the judge:
`missing_env_var` > `test_failure` > `build_failure` > `hardcoded_secret`
> `tests_not_run` > `config_mismatch` > `preprod_check_skipped`
> `pending_migration` > `lockfile_drift` > `unfinished_work`.

---

## 1. `missing_env_var`

**Definition.** Code reads an environment variable that is not set in the
deploy context and has no literal default. The first code path that touches
it crashes (`KeyError`, `undefined`), typically on the first production
request.

**Detection.** Static scan of the source tree:
- Python via AST: `os.environ["X"]`, `os.environ.get("X")`, `os.getenv("X")`.
  Reads *with* a literal default are satisfied; reads without are required.
  Files that fail to parse fall back to a regex scan.
- JS/TS/JSX/Vue via regex: `process.env.X`, `process.env["X"]`,
  `import.meta.env.X` (build-time names `MODE/DEV/PROD/SSR/BASE_URL/NODE_ENV`
  are skipped).
Required names are deduped (first reference wins) and diffed against the
environment the gate runs in.

**Evidence format.** `NAME (file:line)[, NAME (file:line)…] unset` — one
entry per missing variable, anchored at its first read.

**Example record entry.**
```json
{ "name": "env_vars", "type": "deterministic", "passed": false,
  "failure_class": "missing_env_var",
  "evidence": "STRIPE_API_KEY (payments.py:14), DATABASE_URL (db.py:3) unset" }
```

---

## 2. `hardcoded_secret`

**Definition.** A literal credential is committed in the tree. Deploying
publishes it; correctness impact is coupled to config drift (the literal
silently overrides the intended environment-provided value).

**Detection.** Proofjury's `SecretScanner`: provider-shaped regexes — AWS
(`AKIA[0-9A-Z]{16}`), Stripe (`sk_(live|test)_[0-9a-zA-Z]{24,}`), GitHub
(`gh[pousr]_…`), Slack (`xox[baprs]-…`), private-key headers — plus a generic
`(api[_-]?key|secret|token|password) = "…"` pattern gated by Shannon entropy
> 4.0. Placeholders are suppressed (`changeme`, `<your-key-here>`, `${VAR}`,
env-var reads, `example`/`dummy`/`xxx` markers). Binary and lock files are
skipped.

**Evidence format.** `LABEL: PREFIX… (N chars) (file:line)` — the secret
value itself is never persisted (masked prefix only).

**Example record entry.**
```json
{ "name": "secrets", "type": "deterministic", "passed": false,
  "failure_class": "hardcoded_secret",
  "evidence": "Stripe secret key: sk_liv… (32 chars) (billing.py:22)" }
```

---

## 3. `config_mismatch`

**Definition.** Configuration is dev-shaped while the action targets
production: localhost/dev-port URLs, enabled debug flags, test-mode keys,
client-exposed secrets, or an uncommitted-but-unignored `.env.local`.

**Detection.** Line scan of small config-ish files (`config*.py`,
`settings*.py`, `.env*`, `*.toml`, `*.yaml`, `*.yml`, `*.json`) for:
localhost/127.0.0.1 in URL-valued assignments; `DEBUG = True` / `debug: true`;
`sk_test_` keys; dev ports (`:3000`, `:5173`, `:8000`, `:8080`) in host/url
settings; `NEXT_PUBLIC_` names containing KEY/SECRET/TOKEN; `.env.local`
present but not gitignored.

**Evidence format.** `DESCRIPTION (file:line)` per hit, e.g.
`API_BASE_URL points at localhost (config.py:3)`.

**Example record entry.**
```json
{ "name": "config", "type": "deterministic", "passed": false,
  "failure_class": "config_mismatch",
  "evidence": "API_BASE_URL points at localhost (config.py:3), debug mode is enabled (config.py:4)" }
```

---

## 4. `build_failure`

**Definition.** The project defines a build step but no successful build is
recorded for the exact worktree being deployed.

**Detection.** Session marker stamped by `proofjury run build -- <cmd>`:
absent, older than 24h, worktree-digest mismatch, or non-zero exit all fail.
The digest binds the marker to worktree contents (git status + diff + HEAD,
or a content hash outside git). Skipped when no build step exists (no
package.json build script and no `[commands].build` in `.proofjury.toml`).
Builds are never run inline by the gate.

**Evidence format.** `REASON (.proofjury/session.json:1)`, e.g.
`no build recorded for this worktree` or `build failed with exit code 1 (npm run build)`.

**Example record entry.**
```json
{ "name": "build", "type": "deterministic", "passed": false,
  "failure_class": "build_failure",
  "evidence": "code changed since the last build (worktree digest mismatch) (.proofjury/session.json:1)" }
```

---

## 5. `tests_not_run` / `test_failure`

**Definition.** `tests_not_run`: no test run is recorded against this exact
worktree (never ran, ran >24h ago, or code changed since). `test_failure`:
the recorded run exists and failed — deploying ships known-broken code.

**Detection.** Session marker stamped by `proofjury run tests -- <cmd>`
(same digest mechanism as builds). Marker absent/stale/digest-mismatched →
`tests_not_run`; recorded `exit_code != 0` → `test_failure`.

**Evidence format.** `REASON (.proofjury/session.json:1)`, e.g.
`code changed since tests last ran (worktree digest mismatch)` or
`test run failed with exit code 1 (pytest -q)`.

**Example record entry.**
```json
{ "name": "tests", "type": "deterministic", "passed": false,
  "failure_class": "tests_not_run",
  "evidence": "no test run recorded for this worktree (.proofjury/session.json:1)" }
```

---

## 6. `preprod_check_skipped`

**Definition.** Lint/typecheck are configured for the project but were
skipped (or failed) for this worktree — the cheapest available correctness
signal was not consulted before shipping.

**Detection.** Session markers for kinds `lint` and `typecheck` (stamped by
`proofjury run lint|typecheck -- <cmd>`), applicable when configured in
`.proofjury.toml [commands]` or present as package.json scripts; same
freshness/digest rules. Skipped when neither is configured.

**Evidence format.** `KIND REASON (.proofjury/session.json:1)`, e.g.
`lint not run for this worktree` or `typecheck failed with exit code 2`.

**Example record entry.**
```json
{ "name": "preprod", "type": "deterministic", "passed": false,
  "failure_class": "preprod_check_skipped",
  "evidence": "lint not run for this worktree (.proofjury/session.json:1)" }
```

---

## 7. `pending_migration`

**Definition.** An uncommitted change touches a schema source with no
accompanying migration change — the new code would run against the old
schema on deploy.

**Detection.** Diff-scoped, no DB connection: one `git status --porcelain`
call yields the changed set (staged, unstaged, and untracked — a fresh
migration file is usually untracked). Built-in rules: Prisma
(`prisma/schema.prisma` vs `prisma/migrations/`) and Django (`**/models.py`
vs `**/migrations/`). Other stacks opt in via
`.proofjury.toml [checks.migrations] schema = [...] / migrations_dir = "..."`
(alembic is config-only: SQLAlchemy models have no canonical path). Skipped
outside a git repo or when no schema source changed.

**Evidence format.** `schema changed with no change under DIR/ (file:1)`.

**Example record entry.**
```json
{ "name": "migrations", "type": "deterministic", "passed": false,
  "failure_class": "pending_migration",
  "evidence": "schema changed with no change under prisma/migrations/ (prisma/schema.prisma:1)" }
```

---

## 8. `lockfile_drift`

**Definition.** A dependency manifest changed but its committed lockfile
didn't — the deploy installs stale dependencies (or fails resolution),
so the running app doesn't match the manifest the code was written against.

**Detection.** Changed-set scan (same `git status` source): manifest
changed (`package.json`, `pyproject.toml`, `Cargo.toml`, `Gemfile` — at the
root or beside a workspace lockfile) while an EXISTING sibling lockfile
(`package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`/`bun.lock*`,
`uv.lock`/`poetry.lock`, `Cargo.lock`, `Gemfile.lock`) is unchanged.
Projects without a committed lockfile are skipped, not nagged. A
scripts-only manifest edit still fires — label it `false_positive`; the
labels are the correction loop.

**Evidence format.** `changed without LOCKFILE (manifest:1)`.

**Example record entry.**
```json
{ "name": "lockfile", "type": "deterministic", "passed": false,
  "failure_class": "lockfile_drift",
  "evidence": "changed without package-lock.json (package.json:1)" }
```

---

## 9. `unfinished_work`

**Definition.** Newly added lines in the uncommitted diff carry
unfinished-work markers — `TODO`/`FIXME`/`XXX` or `NotImplementedError` —
about to ship to production.

**Detection.** `git diff HEAD -U0` added lines only (diff-scoped, not
tree-scoped: a long-lived committed TODO is a backlog item, not a block).
Markers are matched case-sensitively (uppercase convention) so prose
"todo" never fires. Skipped outside a git repo or with no commits yet.

**Evidence format.** `added line contains MARKER: SNIPPET (file:line)` —
anchored at the added line's post-change line number.

**Example record entry.**
```json
{ "name": "unfinished", "type": "deterministic", "passed": false,
  "failure_class": "unfinished_work",
  "evidence": "added line contains TODO: # TODO: wire this up (app.py:2)" }
```

---

## Rejected design: the "reasoned catch-all" LLM check

Early drafts included a seventh check — an LLM that flags trace-evident
risks the deterministic checklist missed. It was deliberately **not built**,
and is recorded here so it isn't re-proposed as an oversight:

- **Cost discipline.** Every gate run would carry a model call, even when
  all deterministic checks pass — the common case. The shipped judge is
  consulted only *after* a deterministic failure, and only to explain it.
- **Decision integrity.** A check that can fail the gate on model output
  makes pass/fail non-reproducible and un-provable at `file:line`. The
  locked invariant is: deterministic checks decide; the LLM only explains.
- **Offline-first.** The gate must work with no network and no API key; a
  catch-all check would either break that or silently degrade.

New failure classes are added as deterministic checks with `file:line`
evidence (see Versioning below), never as model judgment.

## The advisory surface (tiers 4–5 — never a check, never blocking)

The failure spectrum runs hard/objective → soft/subjective. Tiers 1–2
(doesn't run / functionally wrong) are owned by the compiler and test
suite — Proofjury only enforces that they *ran*. Tier 3 (deploy
readiness) is this taxonomy: the deterministic checks above. Tiers 4–5
(bad engineering / not what was asked) cannot be enumerated as
deterministic classes, so they get a separate, **advisory-only** surface
— distinct from the rejected catch-all above on every axis that killed
it:

- **It cannot block.** Advisory findings never touch `gate_passed`,
  `blocked`, or the exit code, and are stored in a separate `advisories`
  array on the record — never in `checks`, so the deterministic corpus
  stays clean. Decision integrity holds: pass/fail is reproducible and
  provable at `file:line`; the advisory layer only adds context.
- **Cost discipline holds.** It runs only when a key is configured, the
  diff is non-trivial, and the same inputs weren't already reviewed
  (`inputs_hash`); offline the record is byte-identical to a run without
  it.
- **Findings are memory-grounded and human-governed.** Each finding cites
  the prior record ids that informed it (`grounded_in`) and carries a
  confidence-gated delivery state; a human can `approve`, `reject`
  (permanent recurrence suppression + a staged retraction if the agent
  already saw it), or `confirm` each one.

**Graduation, not permanent model enforcement.** A finding signature
confirmed repeatedly surfaces in `memory stats` as a *candidate
deterministic check*: the model discovers the class, a human writes the
`file:line` check, and enforcement moves into this taxonomy through the
normal Versioning path below. The invariant is unchanged — new failure
classes become deterministic checks, never model judgment.

## Versioning

This is v0.2 of an open spec. Additions must be additive (new classes, new
evidence fields); renames or semantic changes to existing classes require a
major version bump, since persisted memory records reference these class
names verbatim.

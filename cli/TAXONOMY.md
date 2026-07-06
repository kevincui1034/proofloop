# Deploy-Time Correctness Failure Taxonomy v0.1

An open specification for the failure classes Proofloop detects at the
deploy boundary. Scope: **correctness, not security** — mistakes an AI
coding agent (or human) makes that break a deployment, not vulnerabilities.

Each class defines: what it is, how it is detected deterministically, the
evidence format persisted with every finding, and an example memory-record
check entry. Evidence is always verifiable against the tree at `file:line`.

Classes are ordered by severity as used by the judge:
`missing_env_var` > `test_failure` > `build_failure` > `hardcoded_secret`
> `tests_not_run` > `config_mismatch` > `preprod_check_skipped`.

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

**Detection.** Proofloop's `SecretScanner`: provider-shaped regexes — AWS
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

**Detection.** Session marker stamped by `proofloop run build -- <cmd>`:
absent, older than 24h, worktree-digest mismatch, or non-zero exit all fail.
The digest binds the marker to worktree contents (git status + diff + HEAD,
or a content hash outside git). Skipped when no build step exists (no
package.json build script and no `[commands].build` in `.proofloop.toml`).
Builds are never run inline by the gate.

**Evidence format.** `REASON (.proofloop/session.json:1)`, e.g.
`no build recorded for this worktree` or `build failed with exit code 1 (npm run build)`.

**Example record entry.**
```json
{ "name": "build", "type": "deterministic", "passed": false,
  "failure_class": "build_failure",
  "evidence": "code changed since the last build (worktree digest mismatch) (.proofloop/session.json:1)" }
```

---

## 5. `tests_not_run` / `test_failure`

**Definition.** `tests_not_run`: no test run is recorded against this exact
worktree (never ran, ran >24h ago, or code changed since). `test_failure`:
the recorded run exists and failed — deploying ships known-broken code.

**Detection.** Session marker stamped by `proofloop run tests -- <cmd>`
(same digest mechanism as builds). Marker absent/stale/digest-mismatched →
`tests_not_run`; recorded `exit_code != 0` → `test_failure`.

**Evidence format.** `REASON (.proofloop/session.json:1)`, e.g.
`code changed since tests last ran (worktree digest mismatch)` or
`test run failed with exit code 1 (pytest -q)`.

**Example record entry.**
```json
{ "name": "tests", "type": "deterministic", "passed": false,
  "failure_class": "tests_not_run",
  "evidence": "no test run recorded for this worktree (.proofloop/session.json:1)" }
```

---

## 6. `preprod_check_skipped`

**Definition.** Lint/typecheck are configured for the project but were
skipped (or failed) for this worktree — the cheapest available correctness
signal was not consulted before shipping.

**Detection.** Session markers for kinds `lint` and `typecheck` (stamped by
`proofloop run lint|typecheck -- <cmd>`), applicable when configured in
`.proofloop.toml [commands]` or present as package.json scripts; same
freshness/digest rules. Skipped when neither is configured.

**Evidence format.** `KIND REASON (.proofloop/session.json:1)`, e.g.
`lint not run for this worktree` or `typecheck failed with exit code 2`.

**Example record entry.**
```json
{ "name": "preprod", "type": "deterministic", "passed": false,
  "failure_class": "preprod_check_skipped",
  "evidence": "lint not run for this worktree (.proofloop/session.json:1)" }
```

---

## Versioning

This is v0.1 of an open spec. Additions must be additive (new classes, new
evidence fields); renames or semantic changes to existing classes require a
major version bump, since persisted memory records reference these class
names verbatim.

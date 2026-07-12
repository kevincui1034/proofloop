# Agent instructions

## Deploy safety — Proofjury gate (required)

Before ANY deploy/release/production-affecting command, route it through
`proofjury guard deploy -- <exact command>`. If BLOCKED (exit 2): read the
evidence, apply the listed fixes, re-run the gate. Never use `--force`
unless the human explicitly instructs it. Run tests via
`proofjury run tests -- <test cmd>` — this is how the gate knows tests ran.

# Agent instructions

## Deploy safety — Proofloop gate (required)

Before ANY deploy/release/production-affecting command, route it through
`proofloop guard deploy -- <exact command>`. If BLOCKED (exit 2): read the
evidence, apply the listed fixes, re-run the gate. Never use `--force`
unless the human explicitly instructs it. Run tests via
`proofloop run tests -- <test cmd>` — this is how the gate knows tests ran.

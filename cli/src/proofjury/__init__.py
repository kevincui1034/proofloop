"""Proofjury — a correctness gate for AI-written code.

`proofjury guard deploy -- <cmd>` runs deterministic readiness checks,
blocks the command when they fail (never spawning it), explains why with
file:line evidence, appends a training-ready JSONL record, and recalls
prior failures so recurrence is caught instantly.
"""

__version__ = "0.1.0"

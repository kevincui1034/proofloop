"""MemoryRecord — one training-ready JSONL record per gate run.

Fields follow the handoff brief §5 exactly, plus additive fields
(schema_version, cli_version, gate_duration_ms, inputs_hash,
env_fingerprint, resolves). The serialized key set is pinned by tests —
do not rename or drop keys casually: the dataset is the company.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1"

#: Serialization order — §5 fields first, additive fields after.
FIELD_ORDER = [
    "id",
    "repo_id",
    "created_at",
    "action_intercepted",
    "agent_source",
    "context_ref",
    "checks",
    "gate_passed",
    "diagnosis",
    "judge_input",
    "judge_output",
    "proof_refs",
    "recalled_from",
    "judge_model_id",
    "resolution",
    # --- additive ---
    "schema_version",
    "cli_version",
    "gate_duration_ms",
    "inputs_hash",
    "env_fingerprint",
    "resolves",
    # --- additive: advisory surface (never enters `checks`) ---
    "advisories",
    "advisory_input",
    "advisory_output",
    "task_ref",
]

#: Keys of each entry in ``checks`` (pinned).
CHECK_ENTRY_KEYS = ["name", "type", "passed", "failure_class", "evidence"]

#: Keys of each entry in ``advisories`` (pinned). Advisory findings are
#: model judgment — recorded and (conditionally) surfaced, NEVER part of
#: the block/allow decision, and never mixed into the ``checks`` array.
ADVISORY_ENTRY_KEYS = [
    "id",             # "<record_id>#<index>", e.g. "chk_012#0"
    "concern",        # what the judge flagged
    "kind",           # "discovery" | "adjudication"
    "tier",           # 4 (bad engineering) | 5 (not what was asked)
    "confidence",     # 0.0–1.0, drives the delivery classification
    "grounded_in",    # prior record ids the finding cited
    "target",         # "file:line" | None
    "judge_model_id",
    "delivery",       # "injected" | "held" | "staged" | "sent" | "suppressed"
    "label",          # None | "confirmed" | "rejected"
    "retraction",     # None | "staged" | "sent" (reject-after-inject only)
]


@dataclass
class MemoryRecord:
    id: str
    repo_id: str
    created_at: str
    action_intercepted: str
    agent_source: str
    context_ref: str
    checks: list[dict]
    gate_passed: bool
    diagnosis: str
    judge_input: str
    judge_output: str
    proof_refs: list[str]
    recalled_from: str | None
    judge_model_id: str
    resolution: dict | None
    schema_version: str = SCHEMA_VERSION
    cli_version: str = "0.1.0"
    gate_duration_ms: int = 0
    inputs_hash: str = ""
    env_fingerprint: list[str] = field(default_factory=list)
    resolves: str | None = None
    advisories: list[dict] = field(default_factory=list)
    advisory_input: str = ""
    advisory_output: str = ""
    task_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = {
            "id": self.id,
            "repo_id": self.repo_id,
            "created_at": self.created_at,
            "action_intercepted": self.action_intercepted,
            "agent_source": self.agent_source,
            "context_ref": self.context_ref,
            "checks": self.checks,
            "gate_passed": self.gate_passed,
            "diagnosis": self.diagnosis,
            "judge_input": self.judge_input,
            "judge_output": self.judge_output,
            "proof_refs": self.proof_refs,
            "recalled_from": self.recalled_from,
            "judge_model_id": self.judge_model_id,
            "resolution": self.resolution,
            "schema_version": self.schema_version,
            "cli_version": self.cli_version,
            "gate_duration_ms": self.gate_duration_ms,
            "inputs_hash": self.inputs_hash,
            "env_fingerprint": self.env_fingerprint,
            "resolves": self.resolves,
            "advisories": self.advisories,
            "advisory_input": self.advisory_input,
            "advisory_output": self.advisory_output,
            "task_ref": self.task_ref,
        }
        return {key: raw[key] for key in FIELD_ORDER}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        return cls(
            id=data["id"],
            repo_id=data.get("repo_id", ""),
            created_at=data.get("created_at", ""),
            action_intercepted=data.get("action_intercepted", ""),
            agent_source=data.get("agent_source", "unknown"),
            context_ref=data.get("context_ref", ""),
            checks=data.get("checks", []),
            gate_passed=bool(data.get("gate_passed", False)),
            diagnosis=data.get("diagnosis", ""),
            judge_input=data.get("judge_input", ""),
            judge_output=data.get("judge_output", ""),
            proof_refs=data.get("proof_refs", []),
            recalled_from=data.get("recalled_from"),
            judge_model_id=data.get("judge_model_id", ""),
            resolution=data.get("resolution"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            cli_version=data.get("cli_version", ""),
            gate_duration_ms=int(data.get("gate_duration_ms", 0)),
            inputs_hash=data.get("inputs_hash", ""),
            env_fingerprint=data.get("env_fingerprint", []),
            resolves=data.get("resolves"),
            advisories=data.get("advisories", []),
            advisory_input=data.get("advisory_input", ""),
            advisory_output=data.get("advisory_output", ""),
            task_ref=data.get("task_ref"),
        )

    def failed_checks(self) -> list[dict]:
        return [c for c in self.checks if not c.get("passed", True)]

    def failure_classes(self) -> set[str]:
        return {
            c["failure_class"]
            for c in self.failed_checks()
            if c.get("failure_class")
        }

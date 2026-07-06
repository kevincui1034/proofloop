"""Judge protocol and the training-ready input/output shapes.

``JudgeInput.to_prompt_text()`` is THE persisted ``judge_input`` for
every engine (deterministic, OpenRouter, mock) — training feature and
runtime prompt are the same string, so the corpus is engine-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..checks.base import CheckResult
from ..memory.schema import MemoryRecord


@dataclass
class JudgeInput:
    action: str
    repo_id: str
    failures: list[CheckResult]
    git_summary: str
    priors: list[MemoryRecord] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = [
            f"Proofloop gate review — action: {self.action}",
            f"Repo: {self.repo_id}",
            "",
            "Failed checks:",
        ]
        if self.failures:
            for result in self.failures:
                lines.append(
                    f"- {result.name} [{result.failure_class}]: {result.evidence_str()}"
                )
                if result.fix_hint:
                    lines.append(f"  suggested fix: {result.fix_hint}")
        else:
            lines.append("- none")
        lines += ["", "Git summary:", self.git_summary or "(unavailable)", "", "Prior related records:"]
        if self.priors:
            for prior in self.priors:
                classes = ", ".join(sorted(prior.failure_classes())) or "unknown"
                evidence = "; ".join(
                    str(c.get("evidence", "")) for c in prior.failed_checks()
                )
                lines.append(f"- {prior.id} ({prior.created_at}) [{classes}]: {evidence}")
        else:
            lines.append("- none")
        lines += [
            "",
            f"Explain why running '{self.action}' now is unsafe and give exact, minimal fix steps.",
        ]
        return "\n".join(lines)


@dataclass
class JudgeOutput:
    diagnosis: str
    fix_steps: list[str]
    model_id: str
    cost_usd: float = 0.0


@runtime_checkable
class Judge(Protocol):
    def diagnose(self, judge_input: JudgeInput) -> JudgeOutput:  # pragma: no cover
        ...

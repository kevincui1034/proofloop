"""DeterministicJudge — offline-first explanation engine.

Per-failure-class templates interpolating the deterministic evidence,
composed severity-first into a single narrative, with a "Seen before"
prefix when memory recalled a prior record. No network, zero cost.
"""

from __future__ import annotations

import re

from .base import JudgeInput, JudgeOutput
from ..checks.base import CheckResult
from ..memory.schema import MemoryRecord

MODEL_ID = "deterministic/proofloop-v1"

#: Worst first: crashes and known-broken code outrank hygiene.
SEVERITY_ORDER = [
    "missing_env_var",
    "test_failure",
    "build_failure",
    "hardcoded_secret",
    "tests_not_run",
    "config_mismatch",
    "preprod_check_skipped",
]

_ENV_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def _severity(result: CheckResult) -> int:
    try:
        return SEVERITY_ORDER.index(result.failure_class or "")
    except ValueError:
        return len(SEVERITY_ORDER)


def _locs(result: CheckResult) -> str:
    return ", ".join(f"{e.file}:{e.line}" for e in result.evidence)


def _sentence(result: CheckResult) -> str:
    cls = result.failure_class
    if cls == "missing_env_var":
        names = ", ".join(e.detail for e in result.evidence)
        return (
            f"{names} referenced ({_locs(result)}) but unset; "
            "the first request will crash."
        )
    if cls == "test_failure":
        detail = result.evidence[0].detail if result.evidence else "tests failed"
        return f"The test suite is failing ({detail}) — this would ship known-broken code."
    if cls == "build_failure":
        detail = result.evidence[0].detail if result.evidence else "build not verified"
        return f"The build is not verified for this worktree ({detail})."
    if cls == "hardcoded_secret":
        return f"Hardcoded secrets are committed in the tree ({_locs(result)})."
    if cls == "tests_not_run":
        detail = result.evidence[0].detail if result.evidence else "no run recorded"
        return f"Tests have not run against this worktree ({detail})."
    if cls == "config_mismatch":
        bits = "; ".join(f"{e.detail} ({e.file}:{e.line})" for e in result.evidence)
        return f"Config is not production-ready: {bits}."
    if cls == "preprod_check_skipped":
        bits = "; ".join(e.detail for e in result.evidence) or "lint/typecheck skipped"
        return f"Pre-production checks were skipped ({bits})."
    return f"{result.name} failed: {result.evidence_str()}."


def _shared_env_names(failures: list[CheckResult], prior: MemoryRecord) -> list[str]:
    current: set[str] = set()
    for result in failures:
        current |= set(_ENV_NAME_RE.findall(result.evidence_str()))
    prior_tokens: set[str] = set()
    for check in prior.failed_checks():
        prior_tokens |= set(_ENV_NAME_RE.findall(str(check.get("evidence", ""))))
    return sorted(current & prior_tokens)


def compile_fix_steps(failures: list[CheckResult]) -> list[str]:
    steps: list[str] = []
    for result in sorted(failures, key=_severity):
        if result.fix_hint and result.fix_hint not in steps:
            steps.append(result.fix_hint)
    return steps


class DeterministicJudge:
    model_id = MODEL_ID

    def diagnose(self, judge_input: JudgeInput) -> JudgeOutput:
        failures = sorted(judge_input.failures, key=_severity)
        sentences = [_sentence(result) for result in failures]

        prefix = ""
        if judge_input.priors:
            prior = judge_input.priors[0]
            shared = _shared_env_names(failures, prior)
            if shared:
                what = f"same {', '.join(shared)} failure"
            elif failures and failures[0].failure_class:
                what = f"same {failures[0].failure_class} failure"
            else:
                what = "same failure"
            prefix = f"Seen before — matches {prior.id} ({prior.created_at}): {what}. "

        if sentences:
            diagnosis = prefix + f"Blocking {judge_input.action} — " + " ".join(sentences)
        else:
            diagnosis = prefix + "All deterministic checks passed."

        return JudgeOutput(
            diagnosis=diagnosis,
            fix_steps=compile_fix_steps(failures),
            model_id=self.model_id,
            cost_usd=0.0,
        )

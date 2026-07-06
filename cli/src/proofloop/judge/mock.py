"""MockJudge — canned output for tests and dry runs."""

from __future__ import annotations

from .base import JudgeInput, JudgeOutput


class MockJudge:
    def __init__(self, output: JudgeOutput | None = None):
        self.output = output or JudgeOutput(
            diagnosis="mock diagnosis",
            fix_steps=["mock fix"],
            model_id="mock/judge",
            cost_usd=0.0,
        )
        self.calls: list[JudgeInput] = []

    def diagnose(self, judge_input: JudgeInput) -> JudgeOutput:
        self.calls.append(judge_input)
        return self.output

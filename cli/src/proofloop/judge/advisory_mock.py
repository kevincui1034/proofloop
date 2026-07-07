"""MockAdvisoryJudge — deterministic fixture findings for tests and the
demo's mock-OpenRouter leg."""

from __future__ import annotations

import json
from dataclasses import asdict

from .advisory import AdvisoryFinding, AdvisoryInput, AdvisoryOutput

DEFAULT_FINDING = AdvisoryFinding(
    concern="The webhook send has no retry or failure handling; a transient "
    "5xx silently drops the notification.",
    kind="discovery",
    tier=4,
    confidence=0.82,
    grounded_in=[],
    target="notifications.py:12",
)


class MockAdvisoryJudge:
    def __init__(
        self,
        findings: list[AdvisoryFinding] | None = None,
        model_id: str = "mock/advisory",
        cost_usd: float = 0.0,
    ):
        self.findings = [DEFAULT_FINDING] if findings is None else list(findings)
        self.model_id = model_id
        self.cost_usd = cost_usd
        self.calls: list[AdvisoryInput] = []

    def review(self, advisory_input: AdvisoryInput) -> AdvisoryOutput:
        self.calls.append(advisory_input)
        raw = json.dumps({"findings": [asdict(f) for f in self.findings]})
        return AdvisoryOutput(
            findings=list(self.findings),
            model_id=self.model_id,
            cost_usd=self.cost_usd,
            raw=raw,
        )

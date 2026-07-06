"""OpenRouterJudge — BYOK LLM explanation with cost ledger + fallback.

Cost discipline: the LLM only *explains* failures, never decides
pass/fail. Any exception (network, parse, HTTP) falls back to the
DeterministicJudge so the gate never depends on a network call.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .base import JudgeInput, JudgeOutput
from .deterministic import DeterministicJudge, compile_fix_steps

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
TIMEOUT_SECONDS = 20.0

SYSTEM_PROMPT = (
    "You are Proofloop's deploy-readiness judge. You receive deterministic "
    "check failures with file:line evidence for a blocked action. Explain "
    "concisely why proceeding now is unsafe and give exact fix steps. "
    'Respond as JSON: {"diagnosis": "<2-4 sentences>", "fix_steps": ["<step>", ...]}.'
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class OpenRouterJudge:
    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        fallback: DeterministicJudge | None = None,
        transport: httpx.BaseTransport | None = None,
        root: Path | None = None,
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.fallback = fallback or DeterministicJudge()
        self.transport = transport  # MockTransport injection point for tests
        self.root = Path(root) if root else None  # .proofloop dir for the ledger

    def diagnose(self, judge_input: JudgeInput) -> JudgeOutput:
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": judge_input.to_prompt_text()},
                ],
                "usage": {"include": True},
            }
            with httpx.Client(transport=self.transport, timeout=TIMEOUT_SECONDS) as client:
                response = client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            content = data["choices"][0]["message"]["content"]
            cost = float((data.get("usage") or {}).get("cost") or 0.0)
            model_id = data.get("model") or self.model
            self._append_ledger(model_id, cost)
            diagnosis, fix_steps = self._parse_content(content, judge_input)
            return JudgeOutput(
                diagnosis=diagnosis,
                fix_steps=fix_steps,
                model_id=model_id,
                cost_usd=cost,
            )
        except Exception:
            return self.fallback.diagnose(judge_input)

    def _append_ledger(self, model: str, cost: float) -> None:
        if self.root is None:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "model": model,
                "cost_usd": cost,
            }
            with (self.root / "ledger.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # the ledger is best-effort; never break a diagnosis over it

    @staticmethod
    def _parse_content(content: str, judge_input: JudgeInput) -> tuple[str, list[str]]:
        text = _FENCE_RE.sub("", content.strip()).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("diagnosis"):
                steps = parsed.get("fix_steps") or []
                if not isinstance(steps, list):
                    steps = [str(steps)]
                return str(parsed["diagnosis"]), [str(s) for s in steps]
        except json.JSONDecodeError:
            pass
        # Unstructured reply: keep it as the diagnosis, compile fixes locally.
        return content.strip(), compile_fix_steps(judge_input.failures)

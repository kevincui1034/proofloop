"""Shared OpenAI chat/completions plumbing for the LLM judge adapters.

OpenAI and OpenRouter speak the same ``/chat/completions`` wire format, so
``ChatCompletionsJudge`` captures everything they share — the SYSTEM_PROMPT,
the request/response shape, fenced-JSON-tolerant parsing, the cost ledger,
fallback-on-exception, and the ``httpx`` transport injection point used by
tests. Subclasses supply only what differs: the endpoint URL, the auth
header, the default model, the request-body extras, and the cost extractor.

The parse/ledger helpers and the token-cost math are module-level so the
Anthropic adapter (a different wire format) can reuse the exact same
behavior without inheriting the chat/completions request path.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .base import JudgeInput, JudgeOutput
from .deterministic import DeterministicJudge, compile_fix_steps

TIMEOUT_SECONDS = 20.0

SYSTEM_PROMPT = (
    "You are Proofjury's deploy-readiness judge. You receive deterministic "
    "check failures with file:line evidence for a blocked action. Explain "
    "concisely why proceeding now is unsafe and give exact fix steps. "
    'Respond as JSON: {"diagnosis": "<2-4 sentences>", "fix_steps": ["<step>", ...]}.'
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_content(content: str, judge_input: JudgeInput) -> tuple[str, list[str]]:
    """Fenced-JSON-tolerant parse of a model reply.

    Returns ``(diagnosis, fix_steps)``. An unstructured reply is kept as the
    diagnosis and the fix steps are compiled locally from the failures.
    """
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
    return content.strip(), compile_fix_steps(judge_input.failures)


def append_ledger(root: Path | None, model: str, cost: float) -> None:
    """Append one ``{ts, model, cost_usd}`` line to ``<root>/ledger.jsonl``.

    Best-effort: a missing root or an OSError never breaks a diagnosis.
    """
    if root is None:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "model": model,
            "cost_usd": cost,
        }
        with (root / "ledger.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def token_cost(
    price: tuple[float, float] | None, input_tokens: int, output_tokens: int
) -> float:
    """USD cost from a ``(input_rate, output_rate)`` pair (USD per 1M tokens).

    Unknown model (``price is None``) → 0.0, matching the offline judge.
    """
    if not price:
        return 0.0
    in_rate, out_rate = price
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


class ChatCompletionsJudge:
    """Base for OpenAI-chat-completions adapters (OpenRouter, OpenAI).

    Any exception (network, parse, HTTP) falls back to the deterministic
    judge so the gate never depends on a network call.
    """

    #: Subclasses set these plus (optionally) override the three hooks below.
    #: ``endpoint_env`` names an env var that overrides ``endpoint`` at
    #: construction time (self-hosted proxy / LiteLLM / test servers).
    endpoint: str = ""
    endpoint_env: str = ""
    default_model: str = ""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        fallback: DeterministicJudge | None = None,
        transport: httpx.BaseTransport | None = None,
        root: Path | None = None,
    ):
        self.api_key = api_key
        self.model = model or self.default_model
        self.fallback = fallback or DeterministicJudge()
        self.transport = transport  # MockTransport injection point for tests
        self.root = Path(root) if root else None  # .proofjury dir for the ledger
        if self.endpoint_env:
            # Instance attribute shadows the class default; unset env → default.
            self.endpoint = os.environ.get(self.endpoint_env) or type(self).endpoint

    # -- subclass hooks --------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _body_extras(self) -> dict:
        return {}

    def _extract_cost(self, data: dict) -> float:
        return 0.0

    # -- shared request path ---------------------------------------------
    def _chat(self, system: str, user: str) -> tuple[str, str, float]:
        """One chat/completions round-trip → ``(content, model_id, cost)``.

        Shared by ``diagnose`` and the advisory judge mixin; exceptions
        propagate — each caller owns its own fallback behavior.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **self._body_extras(),
        }
        headers = {"Content-Type": "application/json", **self._auth_headers()}
        with httpx.Client(transport=self.transport, timeout=TIMEOUT_SECONDS) as client:
            response = client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        cost = self._extract_cost(data)
        model_id = data.get("model") or self.model
        append_ledger(self.root, model_id, cost)
        return content, model_id, cost

    def diagnose(self, judge_input: JudgeInput) -> JudgeOutput:
        try:
            content, model_id, cost = self._chat(
                SYSTEM_PROMPT, judge_input.to_prompt_text()
            )
            diagnosis, fix_steps = parse_content(content, judge_input)
            return JudgeOutput(
                diagnosis=diagnosis,
                fix_steps=fix_steps,
                model_id=model_id,
                cost_usd=cost,
            )
        except Exception:
            return self.fallback.diagnose(judge_input)

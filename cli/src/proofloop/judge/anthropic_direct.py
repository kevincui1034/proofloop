"""AnthropicJudge — direct Anthropic Messages API adapter (raw httpx).

RATIONALE — default model ``claude-haiku-4-5``: the product brief specifies
a *cheap* model for this cost-disciplined judge, which only *explains* a
finding the deterministic checks have already made. Haiku 4.5 is the
cheapest current Claude model ($1 / $5 per 1M input/output tokens), so it is
the default here; override with ``PROOFLOOP_JUDGE_MODEL``.

No ``anthropic`` SDK dependency — Proofloop's judge is provider-neutral, so
this POSTs to the Messages REST endpoint directly, exactly like the
OpenRouter and OpenAI adapters. Shared plumbing (SYSTEM_PROMPT, JSON parse,
ledger, fallback-on-exception, transport injection) is reused from
``_openai_compat``; only the wire shape differs — Anthropic uses a
top-level ``system`` field, ``x-api-key`` auth, and a ``content`` block list
in the response.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ._openai_compat import (
    SYSTEM_PROMPT,
    TIMEOUT_SECONDS,
    append_ledger,
    parse_content,
    token_cost,
)
from .base import JudgeInput, JudgeOutput
from .deterministic import DeterministicJudge

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 700

#: USD per 1M tokens: (input, output). Unknown model → cost 0.0.
PRICE = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}


class AnthropicJudge:
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

    def _chat(self, system: str, user: str) -> tuple[str, str, float]:
        """One Messages-API round-trip → ``(content, model_id, cost)``.

        Shared by ``diagnose`` and the advisory judge mixin; exceptions
        propagate — each caller owns its own fallback behavior.
        """
        payload = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,  # top-level field, not a message
            "messages": [
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        with httpx.Client(transport=self.transport, timeout=TIMEOUT_SECONDS) as client:
            response = client.post(ANTHROPIC_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = self._first_text(data.get("content") or [])
        usage = data.get("usage") or {}
        cost = token_cost(
            PRICE.get(self.model),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
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

    @staticmethod
    def _first_text(blocks: list) -> str:
        """The text of the first ``type == "text"`` content block."""
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text") or ""
        raise ValueError("no text block in Anthropic response")

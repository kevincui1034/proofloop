"""OpenAIJudge — direct OpenAI ``/chat/completions`` adapter (raw httpx).

Symmetric with ``OpenRouterJudge``: same OpenAI chat/completions wire
format (shared via ``ChatCompletionsJudge``), pointed at OpenAI's own
endpoint. OpenAI does not return a per-call cost, so the cost is computed
from ``usage`` token counts against a small local price table.

No ``openai`` SDK dependency — Proofjury's judge is provider-neutral, so
this calls the REST endpoint directly, exactly like the OpenRouter adapter.
"""

from __future__ import annotations

from ._openai_compat import ChatCompletionsJudge, token_cost

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TOKENS = 700

#: USD per 1M tokens: (input, output). Unknown model → cost 0.0.
PRICE = {
    "gpt-4o-mini": (0.15, 0.60),
}


class OpenAIJudge(ChatCompletionsJudge):
    endpoint = OPENAI_URL
    default_model = DEFAULT_MODEL

    def _body_extras(self) -> dict:
        return {"max_tokens": MAX_TOKENS}

    def _extract_cost(self, data: dict) -> float:
        usage = data.get("usage") or {}
        return token_cost(
            PRICE.get(self.model),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

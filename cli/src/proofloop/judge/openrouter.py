"""OpenRouterJudge — BYOK LLM explanation with cost ledger + fallback.

Cost discipline: the LLM only *explains* failures, never decides
pass/fail. Any exception (network, parse, HTTP) falls back to the
DeterministicJudge so the gate never depends on a network call.

Wire format is OpenAI ``/chat/completions``, shared with ``OpenAIJudge``
via ``ChatCompletionsJudge``. OpenRouter-specific: it opts into usage
accounting (``usage.include``) and returns the per-call cost directly on
``usage.cost``, so no local price table is needed.
"""

from __future__ import annotations

from ._openai_compat import ChatCompletionsJudge

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


class OpenRouterJudge(ChatCompletionsJudge):
    endpoint = OPENROUTER_URL
    default_model = DEFAULT_MODEL

    def _body_extras(self) -> dict:
        return {"usage": {"include": True}}

    def _extract_cost(self, data: dict) -> float:
        return float((data.get("usage") or {}).get("cost") or 0.0)

"""Reasoning layer (the judge) — offline-first, cost-disciplined.

The judge only explains failures; deterministic checks own pass/fail.
Provider adapters (OpenRouter, Anthropic, OpenAI) are all raw-httpx and
selected by ``config.resolve_judge`` from env vars + the user config file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .. import config
from .anthropic_direct import AnthropicJudge  # noqa: F401
from .base import Judge, JudgeInput, JudgeOutput  # noqa: F401
from .deterministic import DeterministicJudge  # noqa: F401
from .mock import MockJudge  # noqa: F401
from .openai_direct import OpenAIJudge  # noqa: F401
from .openrouter import DEFAULT_MODEL, OpenRouterJudge  # noqa: F401

_ADAPTERS = {
    "openrouter": OpenRouterJudge,
    "anthropic": AnthropicJudge,
    "openai": OpenAIJudge,
}


def get_judge(env: Mapping[str, str] | None = None, root: Path | None = None) -> Judge:
    """Select a judge from env + user config; deterministic when no LLM."""
    resolved = config.resolve_judge(env)
    if resolved is None:
        return DeterministicJudge()
    adapter = _ADAPTERS.get(resolved["provider"])
    if adapter is None:
        return DeterministicJudge()
    return adapter(
        api_key=resolved["api_key"],
        model=resolved["model"],
        fallback=DeterministicJudge(),
        root=root,
    )

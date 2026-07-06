"""Reasoning layer (the judge) — offline-first, cost-disciplined.

The judge only explains failures; deterministic checks own pass/fail.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .base import Judge, JudgeInput, JudgeOutput  # noqa: F401
from .deterministic import DeterministicJudge  # noqa: F401
from .mock import MockJudge  # noqa: F401
from .openrouter import OpenRouterJudge, DEFAULT_MODEL  # noqa: F401


def get_judge(env: Mapping[str, str] | None = None, root: Path | None = None) -> Judge:
    """OpenRouter when a key is present (and not opted out), else offline."""
    env = os.environ if env is None else env
    api_key = env.get("OPENROUTER_API_KEY")
    if api_key and not env.get("PROOFLOOP_NO_LLM"):
        return OpenRouterJudge(
            api_key=api_key,
            model=env.get("PROOFLOOP_JUDGE_MODEL") or DEFAULT_MODEL,
            fallback=DeterministicJudge(),
            root=root,
        )
    return DeterministicJudge()

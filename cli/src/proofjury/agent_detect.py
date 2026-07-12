"""Detect which coding agent (if any) is driving the current process.

Proofjury is agent-neutral: the detection result is recorded on every
memory record (``agent_source``) for cross-agent analysis, never used to
change gate behaviour.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Mapping


def detect_agent_source(env: Mapping[str, str]) -> str:
    """Return "claude" | "cursor" | "codex" | "unknown" from env markers.

    ``PROOFJURY_AGENT_SOURCE`` overrides everything (useful for adapters
    and tests).
    """
    override = env.get("PROOFJURY_AGENT_SOURCE")
    if override:
        return override
    if env.get("CLAUDECODE") == "1" or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if env.get("CURSOR_TRACE_ID") or env.get("TERM_PROGRAM") == "cursor":
        return "cursor"
    if any(key.startswith("CODEX_") for key in env):
        return "codex"
    return "unknown"


def detect_installed_agents(root: Path) -> list[str]:
    """Best-effort detection of agents installed on this machine / repo.

    Used by ``proofjury init`` to report what it wired up.
    """
    agents: list[str] = []
    if shutil.which("claude") or (root / ".claude").exists():
        agents.append("claude")
    if shutil.which("cursor") or (root / ".cursor").exists():
        agents.append("cursor")
    if shutil.which("codex") or (root / ".codex").exists():
        agents.append("codex")
    return agents

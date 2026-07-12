"""Minimal env-file parser for deploy-env fidelity (``--env-file``).

Deliberately NOT a dotenv clone — the scope is fixed and these are
non-goals, not omissions:

- ``KEY=VALUE`` lines, one per line; optional ``export `` prefix.
- ``#`` full-line comments and blank lines are skipped.
- Surrounding single/double quotes are stripped from values.
- NO variable interpolation (``$VAR`` stays literal).
- NO multiline values, NO inline comments, NO escape processing.

Keeping the parser this small means a value round-trips exactly as the
deploy platform would see it, which is the whole point of evaluating the
``env_vars`` check against the deploy target's environment.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse ``path`` into a name → value dict.

    Raises OSError if the file is missing or unreadable — callers decide
    the failure policy (usage error for --env-file, fail-closed for the
    hook's [env].file config).
    """
    out: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out

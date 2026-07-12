"""config_mismatch — dev-shaped configuration headed for production.

Scans small config-ish files (config*.py, settings*.py, .env*, *.toml,
*.yaml, *.yml, *.json) for localhost URLs, enabled debug flags, test-mode
keys, dev ports in host/url settings, client-exposed secret-looking
NEXT_PUBLIC_ vars, and an un-gitignored .env.local.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .base import CheckContext, CheckResult, Evidence, register, rel

MAX_CONFIG_BYTES = 200_000

_URLISH_KEY = r"[A-Za-z0-9_.\-]*(?:url|host|endpoint|base|api|server|addr)[A-Za-z0-9_.\-]*"

LOCALHOST_URL_RE = re.compile(r"""https?://(?:localhost|127\.0\.0\.1)""", re.IGNORECASE)
# ``["']?`` after the key admits JSON-style quoted keys ("api_host": ...).
LOCALHOST_ASSIGN_RE = re.compile(
    rf"""({_URLISH_KEY})["']?\s*[:=]\s*["']?[^"'\n]*(?:localhost|127\.0\.0\.1)""",
    re.IGNORECASE,
)
DEBUG_RE = re.compile(r"""\b(debug)["']?\s*[:=]\s*["']?(true)\b""", re.IGNORECASE)
SK_TEST_RE = re.compile(r"""sk_test_[0-9a-zA-Z]+""")
DEV_PORT_RE = re.compile(
    rf"""({_URLISH_KEY})["']?\s*[:=]\s*["']?[^"'\n]*:(3000|5173|8000|8080)\b""",
    re.IGNORECASE,
)
NEXT_PUBLIC_SECRET_RE = re.compile(r"""NEXT_PUBLIC_[A-Z0-9_]*(?:KEY|SECRET|TOKEN)[A-Z0-9_]*""")
_KEY_FROM_LINE_RE = re.compile(r"""^\s*["']?([A-Za-z0-9_.\-]+)["']?\s*[:=]""")
_TRIPLE_QUOTE_RE = re.compile(r'"""|\'\'\'')

#: Dev-tool / fixture directories whose configs never reach production.
EXCLUDED_CONFIG_DIRS = {".vscode", ".idea", ".github", "fixtures"}


def is_configish(path: Path, root: Path | None = None) -> bool:
    # Editor/CI/fixture configs (.vscode/launch.json, .github/workflows,
    # tests/fixtures/...) are not deploy config — don't gate on them.
    try:
        parts = path.relative_to(root).parts[:-1] if root else path.parts[:-1]
    except ValueError:
        parts = path.parts[:-1]
    if EXCLUDED_CONFIG_DIRS.intersection(parts):
        return False
    name = path.name.lower()
    if name == "package-lock.json" or path.suffix == ".lock":
        return False
    if name.startswith(".env"):
        return True
    if (name.startswith("config") or name.startswith("settings")) and name.endswith(".py"):
        return True
    return name.endswith((".toml", ".yaml", ".yml", ".json"))


def _key_of(line: str) -> str:
    match = _KEY_FROM_LINE_RE.match(line)
    return match.group(1) if match else "value"


def _strip_inline_comment(line: str) -> str:
    """Drop a trailing ``#`` / ``//`` comment from a config line.

    Quote-aware (a ``#`` or ``//`` inside '…'/"…" is value text) and a
    comment marker must sit at line start or after whitespace — which
    also keeps the ``//`` of unquoted URLs (http://localhost) intact.
    """
    in_quote: str | None = None
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_quote:
            if c == "\\":
                i += 2
                continue
            if c == in_quote:
                in_quote = None
        elif c in "\"'":
            in_quote = c
        elif c == "#" or (c == "/" and i + 1 < n and line[i + 1] == "/"):
            if i == 0 or line[i - 1].isspace():
                return line[:i]
        i += 1
    return line


def _scan_lines(relpath: str, text: str, *, is_python: bool = False) -> list[Evidence]:
    evidence: list[Evidence] = []
    seen_lines: set[int] = set()

    def add(lineno: int, detail: str) -> None:
        if lineno in seen_lines:
            return
        seen_lines.add(lineno)
        evidence.append(Evidence(file=relpath, line=lineno, detail=detail))

    in_docstring = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if is_python:
            # Basic docstring tracker: a line with an odd number of
            # triple-quotes opens/closes a docstring; lines inside (and
            # the delimiter lines themselves) are prose, not config.
            toggles = len(_TRIPLE_QUOTE_RE.findall(line))
            if in_docstring:
                if toggles % 2 == 1:
                    in_docstring = False
                continue
            if toggles % 2 == 1:
                in_docstring = True
                continue
        line = _strip_inline_comment(line)
        stripped = line.strip()
        if stripped.startswith(("#", "//")):
            continue
        if LOCALHOST_URL_RE.search(line) or LOCALHOST_ASSIGN_RE.search(line):
            add(lineno, f"{_key_of(line)} points at localhost")
            continue
        if DEBUG_RE.search(line):
            add(lineno, "debug mode is enabled")
            continue
        if SK_TEST_RE.search(line):
            add(lineno, f"{_key_of(line)} uses a Stripe test-mode key (sk_test_…)")
            continue
        match = DEV_PORT_RE.search(line)
        if match:
            add(lineno, f"{match.group(1)} targets dev port :{match.group(2)}")
            continue
        match = NEXT_PUBLIC_SECRET_RE.search(line)
        if match:
            add(
                lineno,
                f"{match.group(0)} is exposed to the client but its name suggests a secret",
            )
    return evidence


def _env_local_not_ignored(root: Path) -> Evidence | None:
    env_local = root / ".env.local"
    if not env_local.is_file():
        return None
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        try:
            for raw in gitignore.read_text().splitlines():
                pattern = raw.strip().rstrip("/")
                if not pattern or pattern.startswith("#"):
                    continue
                if fnmatch.fnmatch(".env.local", pattern.lstrip("/")):
                    return None
        except OSError:
            pass
    return Evidence(
        file=".env.local",
        line=1,
        detail=".env.local exists but is not gitignored",
    )


@register
def check_config(ctx: CheckContext) -> CheckResult:
    evidence: list[Evidence] = []
    for path in ctx.files:
        if not is_configish(path, ctx.root):
            continue
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        evidence.extend(
            _scan_lines(rel(path, ctx.root), text, is_python=path.suffix == ".py")
        )

    env_local = _env_local_not_ignored(ctx.root)
    if env_local:
        evidence.append(env_local)

    if not evidence:
        return CheckResult(name="config", passed=True)
    return CheckResult(
        name="config",
        passed=False,
        failure_class="config_mismatch",
        evidence=evidence,
        fix_hint=(
            "Point config at production values: replace localhost/dev-port URLs, "
            "disable debug flags, swap test-mode keys for live ones, and gitignore .env.local."
        ),
    )

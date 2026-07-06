"""hardcoded_secret — literal credentials committed into the tree.

Own SecretScanner: provider-shaped regexes plus a generic
keyword-assignment pattern gated by Shannon entropy, with placeholder
suppression so template values don't fire.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections import Counter
from pathlib import Path

from .base import CheckContext, CheckResult, Evidence, register, rel

MAX_FILE_BYTES = 1_000_000

# Entropy gating is per-charset: Shannon entropy is capped by the size of
# the value's alphabet (a hex string can never exceed log2(16) = 4.0 bits
# per char), so a single absolute threshold makes whole charsets
# undetectable. Each threshold is calibrated below that alphabet's
# ceiling: random 16-32 char hex lands around 3.3-3.9 bits, random
# base64-ish values of 24+ chars land around 4.6+, and the generic
# (any-printable) threshold keeps its historical 4.0.
HEX_ENTROPY_THRESHOLD = 3.0
BASE64_ENTROPY_THRESHOLD = 4.5
GENERIC_ENTROPY_THRESHOLD = 4.0

_HEX_VALUE_RE = re.compile(r"[0-9a-fA-F]+\Z")
_BASE64ISH_VALUE_RE = re.compile(r"[A-Za-z0-9+/=_-]+\Z")


def entropy_threshold_for(value: str) -> float:
    """Charset-aware entropy threshold for a candidate secret value."""
    if _HEX_VALUE_RE.fullmatch(value):
        return HEX_ENTROPY_THRESHOLD
    if _BASE64ISH_VALUE_RE.fullmatch(value):
        return BASE64_ENTROPY_THRESHOLD
    return GENERIC_ENTROPY_THRESHOLD


SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "uv.lock",
}


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


class SecretScanner:
    """Line-oriented secret scanner: named provider patterns + generic
    keyword/value pattern gated by entropy."""

    NAMED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("Stripe secret key", re.compile(r"sk_(?:live|test)_[0-9a-zA-Z]{24,}")),
        ("GitHub token", re.compile(r"gh[pousr]_[0-9A-Za-z]{36,}")),
        ("Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
        ("private key material", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ]

    # ``[A-Za-z0-9_-]*`` lets the keyword sit anywhere in the identifier
    # (SECRET_KEY, AWS_SECRET_ACCESS_KEY, API_TOKEN_VALUE, ...), not only
    # immediately before the ``:``/``=``.
    GENERIC_PATTERN = re.compile(
        r"""(api[_-]?key|secret|token|password)[A-Za-z0-9_-]*\s*[:=]\s*["']([^"']{16,})["']""",
        re.IGNORECASE,
    )

    PLACEHOLDER_MARKERS = (
        "changeme",
        "change-me",
        "change_me",
        "your-key",
        "your_key",
        "your-api",
        "your_api",
        "example",
        "dummy",
        "sample",
        "placeholder",
        "xxx",
        "todo",
        "insert",
        "redacted",
    )

    def is_placeholder(self, value: str) -> bool:
        stripped = value.strip()
        lowered = stripped.lower()
        if stripped.startswith("<") and stripped.endswith(">"):
            return True
        if "${" in stripped or lowered.startswith("$"):
            return True
        # env-var reads used as values, not literals
        if "os.environ" in stripped or "os.getenv" in stripped or "process.env" in stripped:
            return True
        return any(marker in lowered for marker in self.PLACEHOLDER_MARKERS)

    @staticmethod
    def _mask(value: str) -> str:
        return f"{value[:6]}… ({len(value)} chars)"

    def scan_line(self, line: str) -> list[str]:
        """Return finding descriptions for one line (no values leaked)."""
        findings: list[str] = []
        for label, pattern in self.NAMED_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if self.is_placeholder(value):
                    continue
                findings.append(f"{label}: {self._mask(value)}")
        for match in self.GENERIC_PATTERN.finditer(line):
            keyword, value = match.group(1), match.group(2)
            if self.is_placeholder(value):
                continue
            if shannon_entropy(value) <= entropy_threshold_for(value):
                continue
            findings.append(
                f"high-entropy {keyword.lower()} literal: {self._mask(value)}"
            )
        return findings

    def should_scan(self, path: Path) -> bool:
        name = path.name
        if name in SKIP_FILENAMES or path.suffix == ".lock":
            return False
        if ".proofloop" in path.parts:
            return False
        if path.suffix in {".min.js", ".map"} or name.endswith(".min.js"):
            return False
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                return False
            head = path.read_bytes()[:8192]
        except OSError:
            return False
        return b"\0" not in head

    def scan_file(self, path: Path, relpath: str) -> list[Evidence]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        evidence: list[Evidence] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            for finding in self.scan_line(line):
                evidence.append(Evidence(file=relpath, line=lineno, detail=finding))
        return evidence


def gitignored_paths(root: Path, paths: list[Path]) -> set[Path]:
    """Subset of ``paths`` that git would ignore.

    A gitignored file (e.g. a proper .env.local) is not "committed into
    the tree", so it is not this check's business. One batched
    ``git check-ignore --stdin -z`` call keeps this fast; outside a git
    repo (or if git is unavailable) returns the empty set, preserving the
    scan-everything behavior.
    """
    root = Path(root)
    rels: list[str] = []
    for p in paths:
        try:
            rels.append(str(Path(p).relative_to(root)))
        except ValueError:
            continue
    if not rels:
        return set()
    try:
        cp = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=root,
            input="\0".join(rels) + "\0",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return set()
    # 0 = some paths ignored, 1 = none ignored; anything else = not a
    # git repo / error, so don't trust the output.
    if cp.returncode not in (0, 1):
        return set()
    return {root / p for p in cp.stdout.split("\0") if p}


@register
def check_secrets(ctx: CheckContext) -> CheckResult:
    scanner = SecretScanner()
    ignored = gitignored_paths(ctx.root, ctx.files)
    evidence: list[Evidence] = []
    for path in ctx.files:
        if path in ignored:
            continue
        if not scanner.should_scan(path):
            continue
        evidence.extend(scanner.scan_file(path, rel(path, ctx.root)))
    if not evidence:
        return CheckResult(name="secrets", passed=True)
    return CheckResult(
        name="secrets",
        passed=False,
        failure_class="hardcoded_secret",
        evidence=evidence,
        fix_hint=(
            "Move the secrets into environment variables (read them at runtime), "
            "delete the literals, and rotate any credential that was committed."
        ),
    )

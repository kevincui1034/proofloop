"""unfinished_work — TODO/FIXME/NotImplementedError in newly ADDED lines.

Diff-scoped, not tree-scoped: a long-lived TODO in committed code is a
backlog item, but one the agent just wrote into the change being shipped is
unfinished work headed for production. Scans only lines added in the
uncommitted diff of tracked files (``git diff HEAD -U0``); an entirely new
untracked file is out of scope for v1.

Skipped outside a git repo, in a repo with no commits, or when nothing
matches.
"""

from __future__ import annotations

import re

from .base import CheckContext, CheckResult, Evidence, register
from .diffbase import added_lines

# Case-sensitive: the uppercase forms are the convention; matching "todo"
# in prose or identifiers would drown the signal in false positives.
_MARKER_RE = re.compile(r"\b(?:TODO|FIXME|XXX)\b|NotImplementedError")


def _marker(text: str) -> str | None:
    match = _MARKER_RE.search(text)
    return match.group(0) if match else None


@register
def check_unfinished(ctx: CheckContext) -> CheckResult:
    lines = added_lines(ctx.root)
    if lines is None:
        return CheckResult(name="unfinished", passed=True, skipped=True)

    evidence: list[Evidence] = []
    for path, lineno, text in lines:
        marker = _marker(text)
        if marker:
            snippet = text.strip()
            if len(snippet) > 80:
                snippet = snippet[:77] + "…"
            evidence.append(
                Evidence(file=path, line=lineno, detail=f"added line contains {marker}: {snippet}")
            )
    if not evidence:
        return CheckResult(name="unfinished", passed=True)
    return CheckResult(
        name="unfinished",
        passed=False,
        failure_class="unfinished_work",
        evidence=evidence,
        fix_hint=(
            "Finish or remove the unfinished-work markers in the added lines "
            "(TODO/FIXME/NotImplementedError) before shipping."
        ),
    )

"""Recall — the optimizer loop's memory read path.

Given the current failures, find prior *blocked* records in the same
repo with overlapping failure classes, ranked by shared evidence tokens
and then recency. Only two token shapes count as evidence: env-var-shaped
ALL_CAPS names (weight 5) and file:line anchors (weight 1). Generic
English words are ignored entirely, so shared session-marker boilerplate
("no test run recorded for this worktree") can never outweigh an exact
env-var-name match. The best match becomes the new record's
``recalled_from``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .schema import MemoryRecord
from .store import MemoryStore

if TYPE_CHECKING:  # pragma: no cover
    from ..checks.base import CheckResult

ENV_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
ANCHOR_RE = re.compile(r"[A-Za-z0-9_./-]+:\d+")

ENV_TOKEN_WEIGHT = 5
ANCHOR_TOKEN_WEIGHT = 1


def _tokens(text: str) -> set[str]:
    """Evidence tokens: env-var-shaped names + file:line anchors ONLY."""
    text = text or ""
    return set(ENV_NAME_RE.findall(text)) | set(ANCHOR_RE.findall(text))


def _failure_tokens(failures: list["CheckResult"]) -> set[str]:
    tokens: set[str] = set()
    for result in failures:
        tokens |= _tokens(result.evidence_str())
        for e in result.evidence:
            tokens |= _tokens(e.detail)
            tokens.add(f"{e.file}:{e.line}")
    return tokens


def _record_tokens(record: MemoryRecord) -> set[str]:
    tokens: set[str] = set()
    for check in record.failed_checks():
        tokens |= _tokens(str(check.get("evidence", "")))
    return tokens


def score_match(current_tokens: set[str], record: MemoryRecord) -> int:
    shared = current_tokens & _record_tokens(record)
    return sum(
        ENV_TOKEN_WEIGHT if ENV_NAME_RE.fullmatch(tok) else ANCHOR_TOKEN_WEIGHT
        for tok in shared
    )


def strong_match(failures: list["CheckResult"], record: MemoryRecord) -> bool:
    """A recurrence strong enough to cite deterministically (no model call):
    identical failure-class set AND at least one shared evidence token."""
    classes = {r.failure_class for r in failures if r.failure_class}
    if not classes or classes != record.failure_classes():
        return False
    return bool(_failure_tokens(failures) & _record_tokens(record))


def recall(
    store: MemoryStore,
    repo_id: str,
    failures: list["CheckResult"],
) -> list[MemoryRecord]:
    """Ranked prior blocked records matching the current failures."""
    classes = {r.failure_class for r in failures if r.failure_class}
    if not classes:
        return []
    current_tokens = _failure_tokens(failures)
    scored: list[tuple[int, str, str, MemoryRecord]] = []
    for record in store.iter_records():
        if record.repo_id != repo_id or record.gate_passed:
            continue
        if not (classes & record.failure_classes()):
            continue
        scored.append(
            (score_match(current_tokens, record), record.created_at, record.id, record)
        )
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [record for *_ignore, record in scored]

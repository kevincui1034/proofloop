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

import dataclasses
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

# Only false_positive is excluded: it marks a block the human judged WRONG.
# overridden / auto_resolved / accepted / confirmed stay recallable — those
# were correct blocks (a --force'd failure is still a true failure, and
# "you forced past this before" is exactly the story recall exists to tell).
EXCLUDED_RESOLUTIONS = frozenset({"false_positive"})

#: A class needs at least this many false_positive labels — and more of
#: them than accepted labels — before it is treated as noisy. One stray
#: label never flips recall behavior.
NOISY_MIN_FALSE_POSITIVES = 2

#: Foreign (cross-repo) priors carry ``<repo_id>:<chk_id>`` ids, qualified
#: at the recall boundary. Repo slugs (owner/repo or a directory name) and
#: chk ids never contain a colon, so its presence is the foreignness test.
FOREIGN_ID_SEP = ":"


def is_foreign_prior(record: MemoryRecord) -> bool:
    """True for a prior recalled from another repo's store (qualified id)."""
    return FOREIGN_ID_SEP in record.id


def class_reliability(store: MemoryStore, repo_id: str | None = None) -> dict[str, dict]:
    """Per-failure-class label counts: which classes' blocks the human
    accepted vs judged false positives.

    Only the two explicit block-correctness labels count — ``accepted``
    and ``false_positive``. ``auto_resolved``/``overridden``/``confirmed``
    are outcomes, not verdicts on whether the block was right. Reads the
    CURRENT top-level resolution status only, never ``history``.
    ``repo_id=None`` aggregates the whole store (used by memory stats).
    """
    counts: dict[str, dict] = {}
    for record in store.iter_records():
        if repo_id is not None and record.repo_id != repo_id:
            continue
        if record.gate_passed:
            continue
        status = (record.resolution or {}).get("status")
        if status not in ("accepted", "false_positive"):
            continue
        for cls in record.failure_classes():
            slot = counts.setdefault(cls, {"accepted": 0, "false_positive": 0})
            slot[status] += 1
    for slot in counts.values():
        slot["noisy"] = (
            slot["false_positive"] >= NOISY_MIN_FALSE_POSITIVES
            and slot["false_positive"] > slot["accepted"]
        )
    return counts


# --------------------------------------------------------------------------
# Advisory suppression — the advisory analog of EXCLUDED_RESOLUTIONS.
# A human `proofjury advisory reject` permanently excludes that finding's
# signature from grounding and re-firing, the way false_positive labels
# keep wrong blocks out of recall.
# --------------------------------------------------------------------------

_ADVISORY_TOKEN_RE = re.compile(r"[a-z0-9_]{4,}")


def advisory_signature(concern: str, target: str | None) -> str:
    """Stable signature for advisory recurrence: the target file (line
    numbers shift) + the salient concern tokens, order-insensitive so a
    reworded restatement of the same concern still matches."""
    file_part = (target or "").split(":", 1)[0].strip().lower()
    tokens = sorted(set(_ADVISORY_TOKEN_RE.findall((concern or "").lower())))
    return file_part + "|" + " ".join(tokens)


def rejected_advisory_signatures(store: MemoryStore, repo_id: str) -> dict[str, str]:
    """``{signature: concern}`` for every human-rejected advisory in the
    repo. The gate drops re-fired findings matching these and lists the
    concerns in the prompt as do-not-re-raise."""
    out: dict[str, str] = {}
    for record in store.iter_records():
        if record.repo_id != repo_id:
            continue
        for entry in record.advisories:
            if entry.get("label") == "rejected":
                signature = advisory_signature(
                    str(entry.get("concern", "")), entry.get("target")
                )
                out[signature] = str(entry.get("concern", ""))
    return out


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
    foreign: list[tuple[str, MemoryStore]] | None = None,
) -> list[MemoryRecord]:
    """Ranked prior blocked records matching the current failures.

    ``foreign`` is other repos' stores (from the user-level registry).
    Foreign matches come back with ``<repo_id>:<chk_id>`` ids and sort as
    a block BELOW every same-repo prior — cross-repo memory is context,
    never the best explanation of a local failure while a local prior
    exists, and never a strong-match short-circuit (guarded at the gate).
    """
    classes = {r.failure_class for r in failures if r.failure_class}
    if not classes:
        return []
    current_tokens = _failure_tokens(failures)
    # Label-informed weighting: a prior whose overlapping classes are ALL
    # noisy (false_positive labels outnumber accepted — see
    # class_reliability) sorts below every prior with a trusted overlap.
    # Demoted, never excluded. With zero labels every class is trusted and
    # ordering is identical to the unweighted behavior.
    reliability = class_reliability(store, repo_id)
    scored: list[tuple[int, int, str, str, MemoryRecord]] = []
    for record in store.iter_records():
        if record.repo_id != repo_id or record.gate_passed:
            continue
        # The gate consumes priors ONLY through recall(), so this filter
        # also keeps false positives out of recalled_from, strong_match
        # short-circuiting, and the judge's cited priors.
        if ((record.resolution or {}).get("status")) in EXCLUDED_RESOLUTIONS:
            continue
        overlap = classes & record.failure_classes()
        if not overlap:
            continue
        trusted = 0 if all(
            reliability.get(cls, {}).get("noisy") for cls in overlap
        ) else 1
        scored.append(
            (trusted, score_match(current_tokens, record), record.created_at, record.id, record)
        )
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    local_priors = [record for *_ignore, record in scored]

    # Foreign segment: same filters, but no repo_id check and no
    # reliability demotion (this repo's labels don't describe another
    # repo's noise). Sorted independently and appended AFTER every local
    # prior, so a foreign record can never displace priors[0].
    foreign_scored: list[tuple[int, str, str, MemoryRecord]] = []
    for f_repo_id, f_store in foreign or []:
        try:
            for record in f_store.iter_records():
                if record.gate_passed:
                    continue
                if ((record.resolution or {}).get("status")) in EXCLUDED_RESOLUTIONS:
                    continue
                if not classes & record.failure_classes():
                    continue
                qualified = dataclasses.replace(
                    record,
                    id=f"{record.repo_id or f_repo_id}{FOREIGN_ID_SEP}{record.id}",
                )
                foreign_scored.append(
                    (
                        score_match(current_tokens, record),
                        record.created_at,
                        qualified.id,
                        qualified,
                    )
                )
        except Exception:
            continue  # one corrupt foreign store never poisons recall
    foreign_scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return local_priors + [record for *_ignore, record in foreign_scored]

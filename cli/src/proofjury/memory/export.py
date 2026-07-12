"""Read-only dataset views over proofjury memory: export rows + stats.

The first consumers of the training labels, ``inputs_hash``, and the
cost ledger. Strictly read-only over ``.proofjury/`` — never appends,
never updates a resolution, never touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .recall import advisory_signature, class_reliability
from .registry import load_registry
from .store import MemoryStore

#: Computed per-row label, derived from the CURRENT resolution status
#: (never from history). This key exists on export rows only — it is
#: never written back into a stored record (FIELD_ORDER is pinned).
UNLABELED = "unlabeled"

#: An advisory signature confirmed this many times is a candidate
#: deterministic check: the model discovered the class, a human writes
#: the file:line check, enforcement moves back to the provable core.
GRADUATION_MIN_CONFIRMED = 3


def row_label(resolution: dict | None) -> str:
    if not isinstance(resolution, dict):
        return UNLABELED
    status = resolution.get("status")
    if not status:
        return UNLABELED
    if status == "confirmed":
        outcome = resolution.get("outcome")
        return f"confirmed:{outcome}" if outcome else "confirmed"
    return str(status)


def export_rows(
    store: MemoryStore,
    *,
    labeled_only: bool = False,
    failure_class: str | None = None,
    dedupe: bool = False,
) -> Iterator[dict]:
    """Training-ready rows: ``record.to_dict()`` plus a computed ``label``.

    ``dedupe`` keeps the LAST record per ``inputs_hash`` (file order ==
    chronological); records with an empty ``inputs_hash`` are never
    deduped — each is kept.
    """
    rows: list[dict] = []
    last_index_for_hash: dict[str, int] = {}
    for record in store.iter_records():
        label = row_label(record.resolution)
        if labeled_only and label == UNLABELED:
            continue
        if failure_class is not None and failure_class not in record.failure_classes():
            continue
        row = record.to_dict()
        row["label"] = label
        if dedupe and record.inputs_hash:
            prev = last_index_for_hash.get(record.inputs_hash)
            if prev is not None:
                rows[prev] = None  # a later record supersedes it
            last_index_for_hash[record.inputs_hash] = len(rows)
        rows.append(row)
    return iter(row for row in rows if row is not None)


def advisory_stats(store: MemoryStore) -> dict:
    """Advisory-surface aggregates + graduation candidates.

    A candidate is a signature (same concern tokens + target file) whose
    findings a human labeled ``confirmed`` at least GRADUATION_MIN_CONFIRMED
    times — proven model judgment ready to become a deterministic check.
    """
    total = 0
    by_delivery: dict[str, int] = {}
    by_label: dict[str, int] = {}
    clusters: dict[str, dict] = {}
    for record in store.iter_records():
        for entry in record.advisories:
            total += 1
            delivery = str(entry.get("delivery") or "unknown")
            by_delivery[delivery] = by_delivery.get(delivery, 0) + 1
            label = str(entry.get("label") or "unlabeled")
            by_label[label] = by_label.get(label, 0) + 1
            if entry.get("label") != "confirmed":
                continue
            signature = advisory_signature(
                str(entry.get("concern", "")), entry.get("target")
            )
            slot = clusters.setdefault(
                signature, {"confirmed": 0, "concern": "", "kind": "", "ids": []}
            )
            slot["confirmed"] += 1
            slot["concern"] = str(entry.get("concern", ""))  # latest wording wins
            slot["kind"] = str(entry.get("kind", ""))
            slot["ids"].append(str(entry.get("id", "")))
    candidates = [
        cluster
        for cluster in clusters.values()
        if cluster["confirmed"] >= GRADUATION_MIN_CONFIRMED
    ]
    candidates.sort(key=lambda c: (-c["confirmed"], c["concern"]))
    return {
        "total": total,
        "by_delivery": by_delivery,
        "by_label": by_label,
        "graduation_candidates": candidates,
    }


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    index = max(0, int(round(0.95 * len(ordered))) - 1)
    return ordered[index]


def read_ledger(ledger_path: Path) -> dict:
    """Aggregate ``{ts, model, cost_usd}`` lines; tolerant of a missing
    file and malformed lines (skip-and-continue, like iter_records)."""
    total = 0.0
    calls = 0
    by_model: dict[str, dict] = {}
    path = Path(ledger_path)
    if path.is_file():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    cost = float(entry.get("cost_usd", 0.0))
                    model = str(entry.get("model", "unknown"))
                except (ValueError, TypeError, AttributeError):
                    continue
                calls += 1
                total += cost
                slot = by_model.setdefault(model, {"calls": 0, "cost_usd": 0.0})
                slot["calls"] += 1
                slot["cost_usd"] += cost
    return {"total_cost_usd": total, "calls": calls, "by_model": by_model}


def stats(store: MemoryStore, ledger_path: Path, *, env=None) -> dict:
    """Dataset health metrics + cost-ledger aggregation."""
    records = 0
    blocked = 0
    passed = 0
    recalled = 0
    cross_repo_hits = 0
    resolves = 0
    failure_classes: dict[str, int] = {}
    labels: dict[str, int] = {}
    agents: dict[str, int] = {}
    durations: list[int] = []
    for record in store.iter_records():
        records += 1
        labels[row_label(record.resolution)] = labels.get(row_label(record.resolution), 0) + 1
        agents[record.agent_source] = agents.get(record.agent_source, 0) + 1
        if record.gate_duration_ms:
            durations.append(record.gate_duration_ms)
        if record.gate_passed:
            passed += 1
            if record.resolves:
                resolves += 1
        else:
            blocked += 1
            if record.recalled_from:
                recalled += 1
                if ":" in record.recalled_from:  # <repo_id>:<chk_id>
                    cross_repo_hits += 1
            for cls in sorted(record.failure_classes()):
                failure_classes[cls] = failure_classes.get(cls, 0) + 1
    return {
        "records": records,
        "blocked": blocked,
        "passed": passed,
        "failure_classes": failure_classes,
        "labels": labels,
        "recall_hit_rate": (recalled / blocked) if blocked else 0.0,
        "auto_resolve_rate": (resolves / passed) if passed else 0.0,
        "gate_duration_ms": {
            "mean": (sum(durations) / len(durations)) if durations else 0.0,
            "p95": _p95(durations) if durations else 0,
        },
        "agents": agents,
        # The input to recall's label-informed weighting, made inspectable:
        # per-class accepted/false_positive counts and the noisy verdict.
        "class_reliability": class_reliability(store),
        "advisories": advisory_stats(store),
        "ledger": read_ledger(ledger_path),
        # Memory recall across this machine's repos: how many stores the
        # user-level registry knows, and how often a block here was
        # explained by a prior from another repo.
        "cross_repo": {
            "registered_repos": len(load_registry(env)["repos"]),
            "recall_hits": cross_repo_hits,
        },
    }

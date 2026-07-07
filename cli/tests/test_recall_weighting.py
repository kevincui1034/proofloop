"""Label-informed recall weighting: noisy classes demote, labels rehabilitate.

The first behavior driven by accumulated labels — memory-recall mechanics
only (no model, no training).
"""

import json

from typer.testing import CliRunner

from proofloop.checks.base import CheckResult, Evidence
from proofloop.cli import app
from proofloop.memory.recall import class_reliability, recall
from proofloop.memory.store import MemoryStore

runner = CliRunner()


def _check(cls: str, name: str = "check", detail: str = "detail") -> dict:
    return {
        "name": name,
        "type": "deterministic",
        "passed": False,
        "failure_class": cls,
        "evidence": detail,
    }


def _failure(cls: str) -> CheckResult:
    return CheckResult(
        name="check",
        passed=False,
        failure_class=cls,
        evidence=[Evidence(file="app.py", line=1, detail="detail")],
    )


def _label(store, record_id, status):
    store.update_resolution(record_id, {"status": status, "at": "t"})


def test_class_reliability_counts_and_noisy_rule(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    for i in (1, 2, 3):
        store.append(record_factory(f"chk_00{i}", checks=[_check("lockfile_drift")]))
    _label(store, "chk_001", "false_positive")
    _label(store, "chk_002", "false_positive")
    _label(store, "chk_003", "accepted")

    reliability = class_reliability(store, "demo-repo")
    assert reliability["lockfile_drift"] == {
        "accepted": 1, "false_positive": 2, "noisy": True,
    }

    # One stray false_positive never flips a class (min threshold = 2)
    store2 = MemoryStore(tmp_path / "other" / ".proofloop")
    store2.append(record_factory("chk_001", checks=[_check("lockfile_drift")]))
    _label(store2, "chk_001", "false_positive")
    assert class_reliability(store2, "demo-repo")["lockfile_drift"]["noisy"] is False


def test_noisy_class_priors_demoted_below_trusted(tmp_path, record_factory):
    """Failure has classes {A, B}. The newest matching prior overlaps only
    on noisy class A → it sorts below an OLDER prior of trusted class B."""
    store = MemoryStore(tmp_path / ".proofloop")
    # Two labeled-false_positive records make lockfile_drift noisy (these
    # two are themselves excluded from recall entirely).
    store.append(record_factory("chk_001", created_at="2026-07-01T00:00:00Z",
                                checks=[_check("lockfile_drift")]))
    store.append(record_factory("chk_002", created_at="2026-07-02T00:00:00Z",
                                checks=[_check("lockfile_drift")]))
    _label(store, "chk_001", "false_positive")
    _label(store, "chk_002", "false_positive")
    # Older trusted-class prior vs newer noisy-class prior:
    store.append(record_factory("chk_003", created_at="2026-07-03T00:00:00Z",
                                checks=[_check("missing_env_var")]))
    store.append(record_factory("chk_004", created_at="2026-07-04T00:00:00Z",
                                checks=[_check("lockfile_drift")]))

    priors = recall(store, "demo-repo",
                    [_failure("lockfile_drift"), _failure("missing_env_var")])
    assert [p.id for p in priors] == ["chk_003", "chk_004"]  # demoted, not excluded


def test_accepted_labels_rehabilitate_class(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    for i, status in enumerate(
        ("false_positive", "false_positive", "accepted", "accepted", "accepted"), start=1
    ):
        store.append(record_factory(f"chk_00{i}", created_at=f"2026-07-0{i}T00:00:00Z",
                                    checks=[_check("lockfile_drift")]))
        _label(store, f"chk_00{i}", status)
    store.append(record_factory("chk_006", created_at="2026-07-06T00:00:00Z",
                                checks=[_check("missing_env_var")]))
    store.append(record_factory("chk_007", created_at="2026-07-07T00:00:00Z",
                                checks=[_check("lockfile_drift")]))

    # accepted (3) >= false_positive (2) → trusted again → recency wins
    priors = recall(store, "demo-repo",
                    [_failure("lockfile_drift"), _failure("missing_env_var")])
    assert priors[0].id == "chk_007"


def test_zero_labels_ordering_unchanged(tmp_path, record_factory):
    """Regression guard: without labels, every class is trusted and the
    ordering is the pre-weighting one (score, then recency)."""
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001", created_at="2026-07-01T00:00:00Z"))
    store.append(record_factory("chk_002", created_at="2026-07-02T00:00:00Z"))
    priors = recall(store, "demo-repo", [_failure("missing_env_var")])
    assert [p.id for p in priors] == ["chk_002", "chk_001"]


def test_stats_exposes_class_reliability(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001", checks=[_check("lockfile_drift")]))
    _label(store, "chk_001", "accepted")
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["memory", "stats", "--json"])
    data = json.loads(result.stdout)
    assert data["class_reliability"]["lockfile_drift"] == {
        "accepted": 1, "false_positive": 0, "noisy": False,
    }

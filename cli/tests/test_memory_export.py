"""Labels change recall; memory export + stats — the dataset's first consumers."""

import json

from typer.testing import CliRunner

from proofloop.cli import app
from proofloop.gate import run_gate
from proofloop.judge import JudgeOutput
from proofloop.judge.mock import MockJudge
from proofloop.memory.export import export_rows, read_ledger, row_label, stats
from proofloop.memory.recall import recall
from proofloop.memory.store import MemoryStore

runner = CliRunner()


def _failure():
    from proofloop.checks.base import CheckResult, Evidence

    return CheckResult(
        name="env_vars",
        passed=False,
        failure_class="missing_env_var",
        evidence=[Evidence(file="payments.py", line=2, detail="STRIPE_API_KEY unset")],
    )


# -- recall exclusion ---------------------------------------------------------


def test_false_positive_prior_excluded_from_recall(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001"))
    store.update_resolution(
        "chk_001", {"status": "false_positive", "note": "CI env", "at": "t1"}
    )
    assert recall(store, "demo-repo", [_failure()]) == []


def test_overridden_prior_still_recalled(tmp_path, record_factory):
    """A --force'd failure is still a true failure — it must stay recallable."""
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001"))
    for status in ("overridden", "accepted", "auto_resolved", "confirmed"):
        store.update_resolution("chk_001", {"status": status, "at": "t"})
        priors = recall(store, "demo-repo", [_failure()])
        assert [p.id for p in priors] == ["chk_001"], status


def test_false_positive_prior_does_not_short_circuit_judge(tmp_repo, scrubbed_env):
    """After labeling the prior false_positive, an identical failure must
    consult the judge (recall no longer short-circuits it) and cite nothing."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    first = run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=dict(scrubbed_env),
        render=False,
    )
    assert first.blocked and first.record.recalled_from is None

    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.update_resolution(
        first.record.id, {"status": "false_positive", "note": None, "at": "t1"}
    )

    judge = MockJudge(
        JudgeOutput(diagnosis="fresh diagnosis", fix_steps=[], model_id="mock/judge", cost_usd=0.0)
    )
    second = run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=dict(scrubbed_env),
        judge=judge, render=False,
    )
    assert second.blocked
    assert second.record.recalled_from is None
    assert len(judge.calls) == 1  # judge actually invoked, not short-circuited


def test_unlabeled_recurrence_still_short_circuits_judge(tmp_repo, scrubbed_env):
    """Regression guard: without the false_positive label, a strong
    recurrence is still cited deterministically — no judge call."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    run_gate(tmp_repo.root, "deploy", None, no_exec=True, env=dict(scrubbed_env), render=False)
    judge = MockJudge()
    second = run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=dict(scrubbed_env),
        judge=judge, render=False,
    )
    assert second.record.recalled_from == "chk_001"
    assert judge.calls == []


# -- export -------------------------------------------------------------------


def test_row_label_derivation():
    assert row_label(None) == "unlabeled"
    assert row_label({}) == "unlabeled"
    assert row_label({"status": "accepted"}) == "accepted"
    assert row_label({"status": "confirmed"}) == "confirmed"
    assert row_label({"status": "confirmed", "outcome": "shipped"}) == "confirmed:shipped"
    assert row_label({"status": "confirmed", "outcome": "rolled_back"}) == "confirmed:rolled_back"


def test_export_labels(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001"))
    store.append(record_factory("chk_002"))
    store.update_resolution("chk_002", {"status": "accepted", "at": "t1"})

    rows = list(export_rows(store))
    assert [r["label"] for r in rows] == ["unlabeled", "accepted"]
    # label is computed on the row only — never stored
    assert "label" not in store.get("chk_001").to_dict()

    labeled = list(export_rows(store, labeled_only=True))
    assert [r["id"] for r in labeled] == ["chk_002"]

    by_class = list(export_rows(store, failure_class="missing_env_var"))
    assert len(by_class) == 2
    assert list(export_rows(store, failure_class="secret_in_code")) == []


def test_export_dedupe_by_inputs_hash(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001", inputs_hash="aaa"))
    store.append(record_factory("chk_002", inputs_hash="aaa"))
    store.append(record_factory("chk_003", inputs_hash="bbb"))
    store.append(record_factory("chk_004", inputs_hash=""))  # never deduped
    store.append(record_factory("chk_005", inputs_hash=""))

    rows = list(export_rows(store, dedupe=True))
    assert [r["id"] for r in rows] == ["chk_002", "chk_003", "chk_004", "chk_005"]


def test_export_cli_jsonl(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    store.append(record_factory("chk_002"))
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["memory", "export"])
    assert result.exit_code == 0
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) == 2
    for line in lines:
        assert "label" in json.loads(line)


def test_export_cli_empty_store(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["memory", "export"])
    assert result.exit_code == 0
    assert result.stdout == ""  # pipeline-safe


def test_export_cli_to_file(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    monkeypatch.chdir(tmp_repo.root)
    out = tmp_repo.root / "dataset.jsonl"
    result = runner.invoke(app, ["memory", "export", "-o", str(out)])
    assert result.exit_code == 0
    assert len(out.read_text().splitlines()) == 1


# -- stats --------------------------------------------------------------------


def test_stats_aggregates_ledger(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001", gate_duration_ms=100))
    store.append(record_factory("chk_002", gate_passed=True, checks=[], gate_duration_ms=300))
    (tmp_repo.root / ".proofloop" / "ledger.jsonl").write_text(
        json.dumps({"ts": "t1", "model": "m1", "cost_usd": 0.0012}) + "\n"
        + "not json\n"  # malformed lines are skipped, never raise
        + json.dumps({"ts": "t2", "model": "m2", "cost_usd": 0.0034}) + "\n"
    )
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["memory", "stats", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data) >= {
        "records", "blocked", "passed", "failure_classes", "labels",
        "recall_hit_rate", "auto_resolve_rate", "gate_duration_ms",
        "agents", "ledger",
    }
    assert data["records"] == 2
    assert data["blocked"] == 1 and data["passed"] == 1
    assert data["failure_classes"] == {"missing_env_var": 1}
    assert data["labels"] == {"unlabeled": 2}
    assert abs(data["ledger"]["total_cost_usd"] - 0.0046) < 1e-9
    assert data["ledger"]["calls"] == 2
    assert data["ledger"]["by_model"]["m1"]["calls"] == 1
    assert data["ledger"]["by_model"]["m2"]["cost_usd"] == 0.0034


def test_stats_empty_store_ok(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["memory", "stats"])
    assert result.exit_code == 0
    assert "no records yet" in result.stdout
    json_result = runner.invoke(app, ["memory", "stats", "--json"])
    data = json.loads(json_result.stdout)
    assert data["records"] == 0
    assert data["ledger"] == {"total_cost_usd": 0.0, "calls": 0, "by_model": {}}


def test_stats_rates(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001"))
    store.append(record_factory("chk_002", recalled_from="chk_001"))
    store.append(
        record_factory("chk_003", gate_passed=True, checks=[], resolves="chk_002")
    )
    data = stats(store, tmp_path / ".proofloop" / "ledger.jsonl")
    assert data["recall_hit_rate"] == 0.5
    assert data["auto_resolve_rate"] == 1.0


def test_read_ledger_missing_file(tmp_path):
    assert read_ledger(tmp_path / "nope.jsonl") == {
        "total_cost_usd": 0.0, "calls": 0, "by_model": {},
    }

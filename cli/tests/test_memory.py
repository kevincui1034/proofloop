"""Memory: schema pin, store roundtrip, recall ranking, resolutions."""

import json
import os
import subprocess
import sys

from typer.testing import CliRunner

from proofloop.checks.base import CheckResult, Evidence
from proofloop.cli import app
from proofloop.memory.recall import recall
from proofloop.memory.schema import CHECK_ENTRY_KEYS, MemoryRecord
from proofloop.memory.store import MemoryStore

runner = CliRunner()

# The dataset is the company: this key set is load-bearing. §5 fields + additive.
EXPECTED_KEYS = {
    # §5 handoff brief fields
    "id",
    "repo_id",
    "created_at",
    "action_intercepted",
    "agent_source",
    "context_ref",
    "checks",
    "gate_passed",
    "diagnosis",
    "judge_input",
    "judge_output",
    "proof_refs",
    "recalled_from",
    "judge_model_id",
    "resolution",
    # additive fields
    "schema_version",
    "cli_version",
    "gate_duration_ms",
    "inputs_hash",
    "env_fingerprint",
    "resolves",
    # additive: advisory surface
    "advisories",
    "advisory_input",
    "advisory_output",
    "task_ref",
}


def test_serialized_key_set_is_pinned(record_factory):
    record = record_factory()
    assert set(record.to_dict().keys()) == EXPECTED_KEYS


def test_check_entry_keys_pinned(record_factory):
    record = record_factory()
    for check in record.to_dict()["checks"]:
        assert set(check.keys()) == set(CHECK_ENTRY_KEYS)


def test_advisory_fields_default_empty_and_roundtrip(tmp_path, record_factory):
    """Old records (no advisory keys) parse; new records default empty."""
    record = record_factory()
    data = record.to_dict()
    assert data["advisories"] == []
    assert data["advisory_input"] == ""
    assert data["advisory_output"] == ""
    assert data["task_ref"] is None
    # a pre-advisory record (missing keys entirely) still parses
    legacy = {k: v for k, v in data.items() if not k.startswith("advisor") and k != "task_ref"}
    parsed = MemoryRecord.from_dict(legacy)
    assert parsed.advisories == []
    assert parsed.task_ref is None
    # advisories roundtrip through the store
    entry = {
        "id": "chk_001#0",
        "concern": "no retry on the webhook POST",
        "kind": "discovery",
        "tier": 4,
        "confidence": 0.8,
        "rubric": None,
        "model_confidence": None,
        "grounded_in": [],
        "target": "notifications.py:12",
        "judge_model_id": "mock/advisory",
        "delivery": "held",
        "label": None,
        "retraction": None,
    }
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_009", advisories=[entry], task_ref="add retries"))
    loaded = store.get("chk_009")
    assert loaded.advisories == [entry]
    assert loaded.task_ref == "add retries"


def test_roundtrip_append_get_iter(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    rec1 = record_factory("chk_001")
    rec2 = record_factory("chk_002", gate_passed=True)
    store.append(rec1)
    store.append(rec2)
    records = list(store.iter_records())
    assert [r.id for r in records] == ["chk_001", "chk_002"]
    fetched = store.get("chk_002")
    assert fetched is not None and fetched.gate_passed
    assert MemoryRecord.from_dict(rec1.to_dict()).to_dict() == rec1.to_dict()


def test_next_id_counter(tmp_path):
    store = MemoryStore(tmp_path / ".proofloop")
    assert store.next_id() == "chk_001"
    assert store.next_id() == "chk_002"
    assert store.next_id() == "chk_003"


def test_next_id_claims_runs_dir_atomically(tmp_path):
    store = MemoryStore(tmp_path / ".proofloop")
    assert store.next_id() == "chk_001"
    assert (store.root / "runs" / "chk_001").is_dir()
    # a pre-existing runs dir is never reused — the id bumps past it
    (store.root / "runs" / "chk_002").mkdir()
    assert store.next_id() == "chk_003"


def test_next_id_never_regresses_below_existing(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_041"))
    (store.root / "runs" / "chk_007").mkdir(parents=True)
    store.counter_path.write_text("2")  # counter regressed / tampered
    assert store.next_id() == "chk_042"


def test_next_id_concurrent_processes_all_unique(tmp_path):
    """~8 concurrent processes allocating ids: all unique, contiguous,
    and the counter lands past the max (regression: unlocked RMW)."""
    root = tmp_path / ".proofloop"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from proofloop.memory.store import MemoryStore\n"
        "store = MemoryStore(Path(sys.argv[1]))\n"
        "ids = [store.next_id() for _ in range(6)]\n"
        "Path(sys.argv[2]).write_text('\\n'.join(ids))\n"
    )
    procs, outs = [], []
    for i in range(8):
        out = tmp_path / f"ids-{i}.txt"
        outs.append(out)
        procs.append(
            subprocess.Popen([sys.executable, "-c", script, str(root), str(out)])
        )
    for proc in procs:
        assert proc.wait() == 0
    ids: list[str] = []
    for out in outs:
        ids.extend(out.read_text().splitlines())
    assert len(ids) == 48
    assert len(set(ids)) == 48, "duplicate ids minted under concurrency"
    numbers = sorted(int(i.split("_")[1]) for i in ids)
    assert numbers == list(range(1, 49))  # monotonic, no gaps, no regression
    assert MemoryStore(root).next_id() == "chk_049"


def test_concurrent_append_and_update_resolution_no_record_loss(tmp_path, record_factory):
    """update_resolution's rewrite must not clobber concurrent appends
    (regression: a prior probe lost ~127/301 records)."""
    root = tmp_path / ".proofloop"
    store = MemoryStore(root)
    store.append(record_factory("chk_900"))
    append_script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from proofloop.memory.store import MemoryStore\n"
        "from proofloop.memory.schema import MemoryRecord\n"
        "store = MemoryStore(Path(sys.argv[1]))\n"
        "base = int(sys.argv[2])\n"
        "for j in range(25):\n"
        "    store.append(MemoryRecord(\n"
        "        id=f'app_{base + j:04d}', repo_id='demo-repo',\n"
        "        created_at='2026-07-01T00:00:00Z', action_intercepted='deploy',\n"
        "        agent_source='unknown', context_ref='', checks=[],\n"
        "        gate_passed=False, diagnosis='', judge_input='',\n"
        "        judge_output='', proof_refs=[], recalled_from=None,\n"
        "        judge_model_id='x', resolution=None))\n"
    )
    update_script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from proofloop.memory.store import MemoryStore\n"
        "store = MemoryStore(Path(sys.argv[1]))\n"
        "for j in range(40):\n"
        "    store.update_resolution('chk_900', {'status': 'accepted', 'note': str(j)})\n"
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", append_script, str(root), str(i * 100)])
        for i in range(4)
    ]
    procs += [
        subprocess.Popen([sys.executable, "-c", update_script, str(root)])
        for _ in range(2)
    ]
    for proc in procs:
        assert proc.wait() == 0
    ids = [r.id for r in store.iter_records()]
    assert len(ids) == 101, f"records lost: expected 101, found {len(ids)}"
    assert len(set(ids)) == 101
    assert store.get("chk_900").resolution["status"] == "accepted"


def test_append_after_crash_truncated_final_line(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001"))
    # Simulate a crash mid-write: the final line loses its trailing bytes.
    data = store.jsonl_path.read_bytes()
    store.jsonl_path.write_bytes(data[:-10])
    store.append(record_factory("chk_002"))
    # The truncated line parse-fails alone; the new record stays intact.
    assert [r.id for r in store.iter_records()] == ["chk_002"]
    lines = store.jsonl_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["id"] == "chk_002"


def test_update_resolution_atomic_rewrite(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    for i in (1, 2, 3):
        store.append(record_factory(f"chk_00{i}"))
    ok = store.update_resolution("chk_002", {"status": "accepted", "note": "yes"})
    assert ok
    records = list(store.iter_records())
    assert records[0].resolution is None
    assert records[1].resolution == {"status": "accepted", "note": "yes"}
    assert records[2].resolution is None
    assert not store.update_resolution("chk_999", {"status": "accepted"})


def test_markdown_appended(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append_markdown(record_factory("chk_001"))
    text = (tmp_path / ".proofloop" / "memory.md").read_text()
    assert "# Proofloop memory" in text
    assert "chk_001" in text
    assert "BLOCKED" in text


def _failure(evidence_name: str, file: str = "payments.py", line: int = 14) -> CheckResult:
    return CheckResult(
        name="env_vars",
        passed=False,
        failure_class="missing_env_var",
        evidence=[Evidence(file=file, line=line, detail=evidence_name)],
        evidence_suffix="unset",
    )


def test_recall_ranks_shared_env_tokens_over_recency(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    match = record_factory("chk_001", created_at="2026-07-01T00:00:00Z")
    unrelated = record_factory(
        "chk_002",
        created_at="2026-07-02T00:00:00Z",  # newer, but different var
        checks=[
            {
                "name": "env_vars",
                "type": "deterministic",
                "passed": False,
                "failure_class": "missing_env_var",
                "evidence": "OTHER_VAR (other.py:1) unset",
            }
        ],
    )
    store.append(match)
    store.append(unrelated)
    ranked = recall(store, "demo-repo", [_failure("STRIPE_API_KEY")])
    assert [r.id for r in ranked] == ["chk_001", "chk_002"]


def test_recall_env_var_match_beats_shared_boilerplate(tmp_path, record_factory):
    """Generic English tokens are ignored: a prior sharing only the
    session-marker boilerplate must not outrank the prior sharing the
    exact env var name (even when the boilerplate one is newer)."""
    store = MemoryStore(tmp_path / ".proofloop")
    env_match = record_factory("chk_001", created_at="2026-07-01T00:00:00Z")
    boilerplate_only = record_factory(
        "chk_002",
        created_at="2026-07-02T00:00:00Z",  # newer
        checks=[
            {
                "name": "tests",
                "type": "deterministic",
                "passed": False,
                "failure_class": "tests_not_run",
                "evidence": "no test run recorded for this worktree (other/marker.json:9)",
            }
        ],
    )
    store.append(env_match)
    store.append(boilerplate_only)
    failures = [
        _failure("STRIPE_API_KEY"),
        CheckResult(
            name="tests",
            passed=False,
            failure_class="tests_not_run",
            evidence=[
                Evidence(
                    file=".proofloop/session.json",
                    line=1,
                    detail="no test run recorded for this worktree",
                )
            ],
        ),
    ]
    ranked = recall(store, "demo-repo", failures)
    assert [r.id for r in ranked] == ["chk_001", "chk_002"]


def test_recall_prefers_recency_on_ties(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001", created_at="2026-07-01T00:00:00Z"))
    store.append(record_factory("chk_002", created_at="2026-07-03T00:00:00Z"))
    ranked = recall(store, "demo-repo", [_failure("STRIPE_API_KEY")])
    assert ranked[0].id == "chk_002"


def test_recall_filters_repo_class_and_passed(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001", repo_id="other-repo"))
    store.append(record_factory("chk_002", gate_passed=True))
    store.append(
        record_factory(
            "chk_003",
            checks=[
                {
                    "name": "config",
                    "type": "deterministic",
                    "passed": False,
                    "failure_class": "config_mismatch",
                    "evidence": "debug mode is enabled (config.py:4)",
                }
            ],
        )
    )
    assert recall(store, "demo-repo", [_failure("STRIPE_API_KEY")]) == []


def test_resolve_cli_updates_record(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(
        app, ["resolve", "chk_001", "--status", "false_positive", "--note", "CI env"]
    )
    assert result.exit_code == 0
    updated = store.get("chk_001")
    assert updated.resolution["status"] == "false_positive"
    assert updated.resolution["note"] == "CI env"


def test_resolve_cli_rejects_bad_status(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["resolve", "chk_001", "--status", "meh"])
    assert result.exit_code == 64  # EX_USAGE — never collides with BLOCKED (2)


def test_confirm_cli_sets_outcome(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["confirm", "chk_001", "--outcome", "rolled_back"])
    assert result.exit_code == 0
    updated = store.get("chk_001")
    assert updated.resolution["status"] == "confirmed"
    assert updated.resolution["outcome"] == "rolled_back"


def test_memory_list_and_show(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    monkeypatch.chdir(tmp_repo.root)
    listed = runner.invoke(app, ["memory", "list"])
    assert listed.exit_code == 0
    assert "chk_001" in listed.stdout
    shown = runner.invoke(app, ["memory", "show", "chk_001"])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["id"] == "chk_001"
    missing = runner.invoke(app, ["memory", "show", "chk_404"])
    assert missing.exit_code == 1


# -- D2: Windows-safe locking -------------------------------------------------


def test_store_importable_without_fcntl(monkeypatch):
    """The module must import on platforms without fcntl (Windows)."""
    import importlib
    import types

    import proofloop.memory.store as store_mod

    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.LK_LOCK = 0
    fake_msvcrt.LK_UNLCK = 1
    fake_msvcrt.locking = lambda *a: None
    monkeypatch.setitem(sys.modules, "fcntl", None)  # forces ImportError
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    try:
        importlib.reload(store_mod)
        assert store_mod.fcntl is None
        assert store_mod.msvcrt is fake_msvcrt
    finally:
        monkeypatch.undo()
        importlib.reload(store_mod)  # restore the POSIX state for other tests
    if os.name == "nt":
        assert store_mod.fcntl is None
    else:
        assert store_mod.fcntl is not None


def test_windows_lock_fallback_serializes(monkeypatch):
    """msvcrt path: seek(0) before lock AND unlock, retry on OSError,
    LK_UNLCK on the same 1-byte range."""
    import types

    import proofloop.memory.store as store_mod

    events: list[tuple] = []

    class FakeFH:
        def seek(self, pos):
            events.append(("seek", pos))

        def fileno(self):
            return 42

    attempts = {"n": 0}

    def fake_locking(fd, mode, nbytes):
        events.append(("locking", fd, mode, nbytes))
        if mode == 100 and attempts["n"] == 0:  # first LK_LOCK fails
            attempts["n"] += 1
            raise OSError("lock violation")

    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.LK_LOCK = 100
    fake_msvcrt.LK_UNLCK = 200
    fake_msvcrt.locking = fake_locking
    monkeypatch.setattr(store_mod, "fcntl", None)
    monkeypatch.setattr(store_mod, "msvcrt", fake_msvcrt, raising=False)
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)

    fh = FakeFH()
    store_mod._lock_file(fh)
    store_mod._unlock_file(fh)

    assert events == [
        ("seek", 0),                # seek(0) before lock
        ("locking", 42, 100, 1),    # LK_LOCK attempt 1 — raises
        ("locking", 42, 100, 1),    # retried until acquired
        ("seek", 0),                # seek(0) before unlock
        ("locking", 42, 200, 1),    # LK_UNLCK on the same 1-byte range
    ]


# -- D3: resolution merge preserves history -----------------------------------


def test_resolution_merge_preserves_history(tmp_path, record_factory):
    store = MemoryStore(tmp_path / ".proofloop")
    store.append(record_factory("chk_001"))
    store.update_resolution(
        "chk_001", {"status": "accepted", "note": None, "at": "t1"}
    )
    first = store.get("chk_001").resolution
    assert first["status"] == "accepted"
    assert "history" not in first  # no prior — looks exactly like today

    store.update_resolution(
        "chk_001", {"status": "confirmed", "outcome": "shipped", "at": "t2"}
    )
    merged = store.get("chk_001").resolution
    assert merged["status"] == "confirmed"
    assert merged["outcome"] == "shipped"
    assert merged["history"] == [{"status": "accepted", "note": None, "at": "t1"}]

    # A third update keeps history flat and chronological (oldest first),
    # each entry stripped of its own history key.
    store.update_resolution(
        "chk_001", {"status": "confirmed", "outcome": "rolled_back", "at": "t3"}
    )
    final = store.get("chk_001").resolution
    assert [h["at"] for h in final["history"]] == ["t1", "t2"]
    assert all("history" not in h for h in final["history"])


def test_confirm_does_not_clobber_auto_resolved(tmp_repo, record_factory, monkeypatch):
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    store.update_resolution(
        "chk_001", {"status": "auto_resolved", "resolved_by": "chk_002", "at": "t1"}
    )
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["confirm", "chk_001", "--outcome", "shipped"])
    assert result.exit_code == 0
    resolution = store.get("chk_001").resolution
    assert resolution["status"] == "confirmed"
    assert resolution["outcome"] == "shipped"
    assert resolution["history"][0]["status"] == "auto_resolved"
    assert resolution["history"][0]["resolved_by"] == "chk_002"


def test_resolve_then_confirm_cli_roundtrip(tmp_repo, record_factory, monkeypatch):
    """Acceptance: resolve → confirm keeps the accepted label in history."""
    store = MemoryStore(tmp_repo.root / ".proofloop")
    store.append(record_factory("chk_001"))
    monkeypatch.chdir(tmp_repo.root)
    assert runner.invoke(app, ["resolve", "chk_001", "--status", "accepted"]).exit_code == 0
    assert runner.invoke(app, ["confirm", "chk_001", "--outcome", "shipped"]).exit_code == 0
    shown = runner.invoke(app, ["memory", "show", "chk_001"])
    data = json.loads(shown.stdout)
    assert data["resolution"]["status"] == "confirmed"
    assert data["resolution"]["outcome"] == "shipped"
    assert data["resolution"]["history"][0]["status"] == "accepted"

"""Advisory labels — approve / reject / confirm, suppression, retraction.

Rejection has exactly three honest effects: the label (training signal),
recurrence suppression (the signature never re-fires or grounds again),
and a staged retraction when the agent already saw the finding. Nothing
here can touch the gate decision.
"""

import pytest
from typer.testing import CliRunner

from proofjury.cli import app
from proofjury.gate import run_gate
from proofjury.judge.advisory import AdvisoryFinding
from proofjury.judge.advisory_mock import MockAdvisoryJudge
from proofjury.memory.recall import advisory_signature, rejected_advisory_signatures
from proofjury.memory.store import MemoryStore
from proofjury.session import stamp

runner = CliRunner()


def _store(root):
    return MemoryStore(root / ".proofjury")


def _finding(concern="the webhook send has no retry", confidence=0.9, target="notifications.py:12"):
    return AdvisoryFinding(
        concern=concern,
        kind="discovery",
        tier=4,
        confidence=confidence,
        grounded_in=[],
        target=target,
    )


@pytest.fixture
def diff_repo(tmp_repo):
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("svc.py", "def add(a, b):\n    return int(a) + int(b)\n")
    return tmp_repo


def _gate(repo, env, judge, edit=None):
    """Run a passing deploy gate; ``edit`` shifts the worktree so the
    advisory inputs_hash cache misses and the judge runs again."""
    if edit:
        repo.write("svc.py", f"def add(a, b):\n    return int(a) + int(b)  # {edit}\n")
    stamp(repo.root, "tests", 0, ["pytest", "-q"])
    return run_gate(
        repo.root, "deploy", None, no_exec=True, env=env, render=False,
        advisory_judge=judge,
    )


# ---------------------------------------------------------------------------
# store.label_advisory
# ---------------------------------------------------------------------------


def test_label_advisory_updates_only_given_fields(diff_repo, scrubbed_env):
    _gate(diff_repo, scrubbed_env, MockAdvisoryJudge(findings=[_finding(confidence=0.5)]))
    store = _store(diff_repo.root)
    assert store.label_advisory("chk_001", 0, delivery="staged")
    entry = store.get("chk_001").advisories[0]
    assert entry["delivery"] == "staged"
    assert entry["label"] is None and entry["retraction"] is None
    assert store.label_advisory("chk_001", 0, label="confirmed")
    entry = store.get("chk_001").advisories[0]
    assert entry["label"] == "confirmed" and entry["delivery"] == "staged"


def test_label_advisory_missing_record_or_index(diff_repo, scrubbed_env):
    _gate(diff_repo, scrubbed_env, MockAdvisoryJudge(findings=[_finding()]))
    store = _store(diff_repo.root)
    assert not store.label_advisory("chk_999", 0, label="confirmed")
    assert not store.label_advisory("chk_001", 5, label="confirmed")


# ---------------------------------------------------------------------------
# CLI lifecycle
# ---------------------------------------------------------------------------


def test_approve_held_then_delivered_next_event(diff_repo, scrubbed_env, monkeypatch):
    judge = MockAdvisoryJudge(findings=[_finding(confidence=0.5)])
    first = _gate(diff_repo, scrubbed_env, judge)
    assert first.record.advisories[0]["delivery"] == "held"
    assert first.agent_notes == []

    monkeypatch.chdir(diff_repo.root)
    result = runner.invoke(app, ["advisory", "approve", "chk_001#0"])
    assert result.exit_code == 0
    assert "next deploy event" in result.output
    assert _store(diff_repo.root).get("chk_001").advisories[0]["delivery"] == "staged"

    second = _gate(diff_repo, scrubbed_env, judge, edit="v2")
    assert any("human-approved advisory chk_001#0" in n for n in second.agent_notes)
    assert _store(diff_repo.root).get("chk_001").advisories[0]["delivery"] == "sent"

    third = _gate(diff_repo, scrubbed_env, judge, edit="v3")
    assert not any("chk_001#0" in n for n in third.agent_notes), "delivered once only"


def test_approve_rejects_non_held(diff_repo, scrubbed_env, monkeypatch):
    _gate(diff_repo, scrubbed_env, MockAdvisoryJudge(findings=[_finding(confidence=0.9)]))
    monkeypatch.chdir(diff_repo.root)
    result = runner.invoke(app, ["advisory", "approve", "chk_001#0"])
    assert result.exit_code == 1
    assert "not held" in result.output


def test_reject_held_suppresses_recurrence(diff_repo, scrubbed_env, monkeypatch):
    judge = MockAdvisoryJudge(findings=[_finding(confidence=0.5)])
    _gate(diff_repo, scrubbed_env, judge)
    monkeypatch.chdir(diff_repo.root)
    result = runner.invoke(app, ["advisory", "reject", "chk_001#0"])
    assert result.exit_code == 0
    assert "will not re-fire" in result.output
    assert "retraction" not in result.output, "held was never delivered"
    entry = _store(diff_repo.root).get("chk_001").advisories[0]
    assert entry["label"] == "rejected" and entry["retraction"] is None

    # the same concern — even reworded — never fires again
    reworded = MockAdvisoryJudge(
        findings=[_finding(concern="webhook send: no retry", confidence=0.9)]
    )
    again = _gate(diff_repo, scrubbed_env, reworded, edit="v2")
    assert again.record.advisories == []
    assert len(reworded.calls) == 1, "the judge ran; its re-fire was dropped"
    # and the prompt told it not to re-raise
    assert "the webhook send has no retry" in again.record.advisory_input


def test_reject_injected_stages_retraction(diff_repo, scrubbed_env, monkeypatch):
    judge = MockAdvisoryJudge(findings=[_finding(confidence=0.9)])
    first = _gate(diff_repo, scrubbed_env, judge)
    assert first.record.advisories[0]["delivery"] == "injected"

    monkeypatch.chdir(diff_repo.root)
    result = runner.invoke(app, ["advisory", "reject", "chk_001#0"])
    assert result.exit_code == 0
    assert "retraction note goes to the agent" in result.output
    entry = _store(diff_repo.root).get("chk_001").advisories[0]
    assert entry["label"] == "rejected" and entry["retraction"] == "staged"

    second = _gate(diff_repo, scrubbed_env, judge, edit="v2")
    assert any("Disregard advisory chk_001#0" in n for n in second.agent_notes)
    assert _store(diff_repo.root).get("chk_001").advisories[0]["retraction"] == "sent"


def test_reject_staged_cancels_delivery(diff_repo, scrubbed_env, monkeypatch):
    """Approve then reject before the next event: the note must NOT go out."""
    judge = MockAdvisoryJudge(findings=[_finding(confidence=0.5)])
    _gate(diff_repo, scrubbed_env, judge)
    monkeypatch.chdir(diff_repo.root)
    assert runner.invoke(app, ["advisory", "approve", "chk_001#0"]).exit_code == 0
    assert runner.invoke(app, ["advisory", "reject", "chk_001#0"]).exit_code == 0
    second = _gate(diff_repo, scrubbed_env, judge, edit="v2")
    assert not any("chk_001#0" in n for n in second.agent_notes)


def test_confirm_labels_finding(diff_repo, scrubbed_env, monkeypatch):
    _gate(diff_repo, scrubbed_env, MockAdvisoryJudge(findings=[_finding(confidence=0.9)]))
    monkeypatch.chdir(diff_repo.root)
    result = runner.invoke(app, ["advisory", "confirm", "chk_001#0"])
    assert result.exit_code == 0
    assert _store(diff_repo.root).get("chk_001").advisories[0]["label"] == "confirmed"


def test_cli_ref_validation(diff_repo, scrubbed_env, monkeypatch):
    monkeypatch.chdir(diff_repo.root)
    for bad in ("chk_001", "chk_001#x", "#0"):
        result = runner.invoke(app, ["advisory", "reject", bad])
        assert result.exit_code == 64, bad  # EX_USAGE
    assert runner.invoke(app, ["advisory", "reject", "chk_404#0"]).exit_code == 1
    _gate(diff_repo, scrubbed_env, MockAdvisoryJudge(findings=[_finding()]))
    assert runner.invoke(app, ["advisory", "reject", "chk_001#7"]).exit_code == 1


# ---------------------------------------------------------------------------
# signatures
# ---------------------------------------------------------------------------


def test_advisory_signature_is_rewording_stable():
    a = advisory_signature("The webhook send has no retry", "notifications.py:12")
    b = advisory_signature("no retry on the webhook send!", "notifications.py:99")
    assert a == b, "same tokens + same file (line shifts) → same signature"
    c = advisory_signature("The webhook send has no retry", "other.py:1")
    assert a != c, "a different file is a different finding"
    d = advisory_signature("missing index on lookups", "notifications.py:12")
    assert a != d


# ---------------------------------------------------------------------------
# graduation — confirmed signatures become candidate deterministic checks
# ---------------------------------------------------------------------------


def _confirmed_entry(record_id, concern="deploy script ignores curl failures", label="confirmed"):
    return {
        "id": f"{record_id}#0", "concern": concern, "kind": "discovery",
        "tier": 4, "confidence": 0.9, "grounded_in": [], "target": "deploy.sh:3",
        "judge_model_id": "m", "delivery": "injected", "label": label,
        "retraction": None,
    }


def test_graduation_candidate_after_three_confirmations(record_factory, tmp_path):
    from proofjury.memory.export import advisory_stats

    store = MemoryStore(tmp_path / ".proofjury")
    for i in (1, 2, 3):
        rid = f"chk_00{i}"
        store.append(record_factory(rid, advisories=[_confirmed_entry(rid)]))
    # two confirmations of a DIFFERENT signature → not a candidate
    for i in (4, 5):
        rid = f"chk_00{i}"
        store.append(
            record_factory(
                rid, advisories=[_confirmed_entry(rid, concern="missing db index")]
            )
        )
    data = advisory_stats(store)
    assert data["total"] == 5
    assert data["by_label"] == {"confirmed": 5}
    candidates = data["graduation_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["confirmed"] == 3
    assert "curl failures" in candidates[0]["concern"]
    assert candidates[0]["ids"] == ["chk_001#0", "chk_002#0", "chk_003#0"]


def test_memory_stats_cli_shows_candidates(record_factory, tmp_repo, monkeypatch):
    import json as json_module

    store = _store(tmp_repo.root)
    for i in (1, 2, 3):
        rid = f"chk_00{i}"
        store.append(record_factory(rid, advisories=[_confirmed_entry(rid)]))
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["memory", "stats"])
    assert result.exit_code == 0
    assert "Candidate deterministic checks" in result.output
    assert "×3 confirmed" in result.output
    json_result = runner.invoke(app, ["memory", "stats", "--json"])
    data = json_module.loads(json_result.output)
    assert data["advisories"]["graduation_candidates"][0]["confirmed"] == 3


def test_render_advisories_shows_every_finding(diff_repo, scrubbed_env):
    """The human sees every finding, whatever its delivery tier."""
    import io

    from rich.console import Console

    from proofjury import ux

    judge = MockAdvisoryJudge(
        findings=[
            _finding(concern="high risk concern", confidence=0.9),
            _finding(concern="held hunch", confidence=0.5),
            _finding(concern="noise floor item", confidence=0.1),
        ]
    )
    result = _gate(diff_repo, scrubbed_env, judge)
    buffer = io.StringIO()
    console = Console(file=buffer, width=120, no_color=True)
    ux.render_advisories(console, result.record, result.agent_notes)
    output = buffer.getvalue()
    assert "model judgment, not blocking" in output
    assert "high risk concern" in output and "sent to agent" in output
    assert "held hunch" in output and "awaiting your approval" in output
    assert "advisory approve chk_001#1" in output  # the held one is actionable
    assert "noise floor item" in output and "recorded only" in output
    # empty record renders nothing
    empty_buffer = io.StringIO()
    empty_console = Console(file=empty_buffer, width=120, no_color=True)
    second = _gate(diff_repo, scrubbed_env, MockAdvisoryJudge(findings=[]), edit="v2")
    ux.render_advisories(empty_console, second.record, second.agent_notes)
    assert empty_buffer.getvalue() == ""


def test_rejected_advisory_signatures_scoped_to_repo(record_factory, tmp_path):
    store = MemoryStore(tmp_path / ".proofjury")
    entry = {
        "id": "chk_001#0", "concern": "no retry on webhook", "kind": "discovery",
        "tier": 4, "confidence": 0.8, "grounded_in": [], "target": "n.py:1",
        "judge_model_id": "m", "delivery": "held", "label": "rejected",
        "retraction": None,
    }
    other = dict(entry, id="chk_002#0", label="confirmed")
    store.append(record_factory("chk_001", repo_id="repo-a", advisories=[entry]))
    store.append(record_factory("chk_002", repo_id="repo-b", advisories=[dict(entry, id="chk_002#0")]))
    store.append(record_factory("chk_003", repo_id="repo-a", advisories=[other]))
    rejected = rejected_advisory_signatures(store, "repo-a")
    assert list(rejected.values()) == ["no retry on webhook"]
    assert rejected_advisory_signatures(store, "repo-c") == {}

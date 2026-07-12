"""Advisory surface — config, task capture, the judge, and gate step 3.5.

The advisory judge is model judgment that NEVER blocks: deterministic
checks alone own blocked/exit_code. These tests pin that invariant.
"""

import json

import httpx
import pytest

from proofjury.config import ADVISORY_DEFAULTS, advisory_settings
from proofjury.gate import resolve_task_ref, run_gate
from proofjury.hooks import task_from_payload
from proofjury.judge.advisory import (
    AdvisoryFinding,
    AdvisoryInput,
    OpenRouterAdvisoryJudge,
    parse_findings,
)
from proofjury.judge.advisory_mock import MockAdvisoryJudge
from proofjury.memory.schema import ADVISORY_ENTRY_KEYS, CHECK_ENTRY_KEYS
from proofjury.memory.store import MemoryStore
from proofjury.session import stamp


def _store(root):
    return MemoryStore(root / ".proofjury")


def _finding(
    concern="the webhook send has no retry",
    kind="discovery",
    tier=4,
    confidence=0.9,
    target="notifications.py:12",
    grounded_in=None,
):
    return AdvisoryFinding(
        concern=concern,
        kind=kind,
        tier=tier,
        confidence=confidence,
        grounded_in=grounded_in or [],
        target=target,
    )


@pytest.fixture
def diff_repo(tmp_repo):
    """A git repo with a committed base and an uncommitted edit, so the
    gate sees a non-trivial diff (the advisory judge's entry condition)."""
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("svc.py", "def add(a, b):\n    return int(a) + int(b)\n")
    return tmp_repo


def _pass_gate(repo, env, **kwargs):
    """Run a passing deploy gate (tests stamped after the last edit)."""
    stamp(repo.root, "tests", 0, ["pytest", "-q"])
    return run_gate(
        repo.root, "deploy", None, no_exec=True, env=env, render=False, **kwargs
    )


def _blocked_gate(repo, env, **kwargs):
    """Run a blocked deploy gate (tests never stamped → tests_not_run)."""
    return run_gate(
        repo.root, "deploy", None, no_exec=True, env=env, render=False, **kwargs
    )


# ---------------------------------------------------------------------------
# [advisory] settings
# ---------------------------------------------------------------------------


def test_advisory_settings_defaults():
    assert advisory_settings({}) == ADVISORY_DEFAULTS
    assert advisory_settings(None) == ADVISORY_DEFAULTS
    assert advisory_settings({"advisory": "not-a-table"}) == ADVISORY_DEFAULTS


def test_advisory_settings_overrides():
    settings = advisory_settings(
        {
            "advisory": {
                "enabled": False,
                "auto_inject_min_confidence": 0.9,
                "hold_min_confidence": 0.5,
                "max_findings": 2,
                "diff_min_lines": 10,
                "tiers": [4],
                "model": "openai/gpt-4o",
            }
        }
    )
    assert settings["enabled"] is False
    assert settings["auto_inject_min_confidence"] == 0.9
    assert settings["hold_min_confidence"] == 0.5
    assert settings["max_findings"] == 2
    assert settings["diff_min_lines"] == 10
    assert settings["tiers"] == [4]
    assert settings["model"] == "openai/gpt-4o"


def test_advisory_settings_malformed_values_fall_back():
    settings = advisory_settings(
        {
            "advisory": {
                "enabled": "yes",  # not a bool
                "auto_inject_min_confidence": 7,  # clamped to 1.0
                "hold_min_confidence": "high",  # not numeric
                "max_findings": -3,  # negative
                "tiers": [1, 2, "four", 5],  # only valid tiers kept
                "model": "   ",  # blank
            }
        }
    )
    assert settings["enabled"] is True
    assert settings["auto_inject_min_confidence"] == 1.0
    assert settings["hold_min_confidence"] == ADVISORY_DEFAULTS["hold_min_confidence"]
    assert settings["max_findings"] == ADVISORY_DEFAULTS["max_findings"]
    assert settings["tiers"] == [5]
    assert settings["model"] is None


# ---------------------------------------------------------------------------
# task_ref capture
# ---------------------------------------------------------------------------


def test_resolve_task_ref_precedence():
    config = {"session": {"task": "from config"}}
    env = {"PROOFJURY_TASK": "from env"}
    assert resolve_task_ref("explicit", env, config) == "explicit"
    assert resolve_task_ref(None, env, config) == "from env"
    assert resolve_task_ref(None, {}, config) == "from config"
    assert resolve_task_ref(None, {}, {}) is None
    assert resolve_task_ref("   ", {}, {}) is None


def test_resolve_task_ref_normalizes_and_bounds():
    task = resolve_task_ref("add\n  rate   limiting\t here", {}, {})
    assert task == "add rate limiting here"
    long = resolve_task_ref("x" * 1000, {}, {})
    assert len(long) == 400


def test_task_ref_lands_in_record_and_context(tmp_repo, scrubbed_env):
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest", "-q"])
    result = run_gate(
        tmp_repo.root,
        "deploy",
        None,
        no_exec=True,
        env=scrubbed_env,
        task_ref="add rate limiting",
        render=False,
    )
    assert result.record.task_ref == "add rate limiting"
    context = json.loads(
        (tmp_repo.root / ".proofjury" / "runs" / result.record.id / "context.json").read_text()
    )
    assert context["task_ref"] == "add rate limiting"
    # and it survives the store roundtrip
    assert _store(tmp_repo.root).get(result.record.id).task_ref == "add rate limiting"


def test_task_ref_absent_by_default(tmp_repo, scrubbed_env):
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    result = run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=scrubbed_env, render=False
    )
    assert result.record.task_ref is None


def test_task_ref_env_values_scrubbed(tmp_repo, scrubbed_env):
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    env = dict(scrubbed_env, DEPLOY_TOKEN="supersecretvalue123")
    result = run_gate(
        tmp_repo.root,
        "deploy",
        None,
        no_exec=True,
        env=env,
        task_ref="rotate supersecretvalue123 in prod",
        render=False,
    )
    assert "supersecretvalue123" not in result.record.task_ref
    assert "[REDACTED]" in result.record.task_ref


# ---------------------------------------------------------------------------
# transcript capture (hook payloads)
# ---------------------------------------------------------------------------


def test_task_from_payload_reads_last_user_message(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "old task"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "on it"}},
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "add rate limiting"}],
            },
        },
        {"type": "assistant", "message": {"role": "assistant", "content": "done"}},
    ]
    transcript.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    assert task_from_payload({"transcript_path": str(transcript)}) == "add rate limiting"


def test_task_from_payload_skips_non_text_user_entries(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "real task"}},
        # tool_result-style user entry: no text blocks — must be skipped
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}],
            },
        },
    ]
    transcript.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    assert task_from_payload({"transcript_path": str(transcript)}) == "real task"


def test_task_from_payload_best_effort_none():
    assert task_from_payload({}) is None
    assert task_from_payload({"transcript_path": "/nonexistent/x.jsonl"}) is None
    assert task_from_payload({"transcript_path": None}) is None


# ---------------------------------------------------------------------------
# parse_findings — strict JSON, malformed findings dropped
# ---------------------------------------------------------------------------


def test_parse_findings_valid_and_fenced():
    payload = {
        "findings": [
            {
                "concern": "no retry\n  on the POST",
                "kind": "discovery",
                "tier": 4,
                "confidence": 0.8,
                "grounded_in": ["chk_001", "chk_999"],
                "target": "a.py:1",
            }
        ]
    }
    for content in (json.dumps(payload), f"```json\n{json.dumps(payload)}\n```"):
        findings = parse_findings(content, known_ids={"chk_001"})
        assert len(findings) == 1
        f = findings[0]
        assert f.concern == "no retry on the POST"  # whitespace normalized
        assert f.grounded_in == ["chk_001"]  # hallucinated id filtered
        assert f.target == "a.py:1"


def test_parse_findings_drops_malformed():
    payload = {
        "findings": [
            {"concern": "", "kind": "discovery", "tier": 4, "confidence": 0.5},
            {"concern": "x", "kind": "blocking", "tier": 4, "confidence": 0.5},
            {"concern": "x", "kind": "discovery", "tier": 3, "confidence": 0.5},
            {"concern": "x", "kind": "discovery", "tier": 4, "confidence": "high"},
            {"concern": "x", "kind": "discovery", "tier": 4, "confidence": True},
            "not-a-dict",
            {"concern": "ok", "kind": "adjudication", "tier": 5, "confidence": 2.5,
             "grounded_in": "chk_001", "target": 42},
        ]
    }
    findings = parse_findings(json.dumps(payload), known_ids=set())
    assert len(findings) == 1
    assert findings[0].concern == "ok"
    assert findings[0].confidence == 1.0  # clamped
    assert findings[0].grounded_in == []  # non-list dropped
    assert findings[0].target is None  # non-str dropped


def test_parse_findings_garbage_returns_empty():
    assert parse_findings("not json at all", set()) == []
    assert parse_findings('{"findings": "nope"}', set()) == []
    assert parse_findings('["list"]', set()) == []
    assert parse_findings("", set()) == []


# ---------------------------------------------------------------------------
# gate step 3.5 — classification, invariants, entry conditions
# ---------------------------------------------------------------------------


def test_passing_gate_high_confidence_finding_injected(diff_repo, scrubbed_env):
    judge = MockAdvisoryJudge()
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert result.exit_code == 0 and result.record.gate_passed
    assert len(judge.calls) == 1
    record = result.record
    assert len(record.advisories) == 1
    entry = record.advisories[0]
    assert entry["id"] == f"{record.id}#0"
    assert entry["delivery"] == "injected"
    assert entry["kind"] == "discovery" and entry["tier"] == 4
    assert entry["judge_model_id"] == "mock/advisory"
    assert entry["label"] is None and entry["retraction"] is None
    assert record.advisory_input.startswith("Proofjury advisory review")
    assert json.loads(record.advisory_output)["findings"]
    assert len(result.agent_notes) == 1
    assert entry["id"] in result.agent_notes[0]
    assert "NOT blocking" in result.agent_notes[0]


def test_advisory_entry_keys_pinned(diff_repo, scrubbed_env):
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=MockAdvisoryJudge())
    for entry in result.record.advisories:
        assert list(entry.keys()) == ADVISORY_ENTRY_KEYS
    # and advisories never leak into the checks array
    for check in result.record.to_dict()["checks"]:
        assert set(check.keys()) == set(CHECK_ENTRY_KEYS)


def test_confidence_gates_drive_delivery(diff_repo, scrubbed_env):
    judge = MockAdvisoryJudge(
        findings=[
            _finding(concern="high confidence risk", confidence=0.9),
            _finding(concern="medium confidence hunch", confidence=0.5),
            _finding(concern="low confidence noise", confidence=0.1),
        ]
    )
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    deliveries = [e["delivery"] for e in result.record.advisories]
    assert deliveries == ["injected", "held", "suppressed"]
    # only the injected finding reaches the agent
    assert len(result.agent_notes) == 1
    assert "high confidence risk" in result.agent_notes[0]


def test_exit_code_identical_with_and_without_advisories(tmp_repo, scrubbed_env):
    """THE invariant: deterministic checks alone own blocked/exit_code."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n# v2\n')
    judge = MockAdvisoryJudge(
        findings=[_finding(confidence=0.99), _finding(concern="second", confidence=0.99)]
    )
    blocked_with = _blocked_gate(tmp_repo, scrubbed_env, advisory_judge=judge)
    assert blocked_with.record.advisories and blocked_with.agent_notes
    blocked_without = _blocked_gate(tmp_repo, scrubbed_env)
    assert not blocked_without.record.advisories
    assert blocked_with.blocked and blocked_without.blocked
    assert blocked_with.exit_code == blocked_without.exit_code == 2

    # and on a passing run
    stamp(tmp_repo.root, "tests", 0, ["pytest", "-q"])
    env = dict(scrubbed_env, STRIPE_API_KEY="sk_test_x")
    with_adv = run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=env, render=False,
        advisory_judge=MockAdvisoryJudge(),
    )
    assert with_adv.exit_code == 0 and with_adv.record.advisories


def test_offline_no_llm_yields_empty_advisories(diff_repo, scrubbed_env):
    """No key, no config → no advisory judge; record shape unchanged."""
    result = _pass_gate(diff_repo, scrubbed_env)
    assert result.record.advisories == []
    assert result.record.advisory_input == ""
    assert result.record.advisory_output == ""
    assert result.agent_notes == []


def test_advisory_disabled_in_config_skips_judge(diff_repo, scrubbed_env):
    diff_repo.write(".proofjury.toml", "[advisory]\nenabled = false\n")
    judge = MockAdvisoryJudge()
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert judge.calls == []
    assert result.record.advisories == []


def test_trivial_diff_skips_judge(diff_repo, scrubbed_env):
    diff_repo.write(".proofjury.toml", "[advisory]\ndiff_min_lines = 500\n")
    judge = MockAdvisoryJudge()
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert judge.calls == []
    assert result.record.advisories == []


def test_inputs_hash_cache_skips_second_review(diff_repo, scrubbed_env):
    judge = MockAdvisoryJudge()
    first = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert len(judge.calls) == 1 and first.record.advisories
    second = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert len(judge.calls) == 1, "identical inputs must not re-run the model"
    assert second.record.advisories == []


def test_tier_5_requires_task_ref(diff_repo, scrubbed_env):
    tier5 = _finding(concern="does not match the task", kind="discovery", tier=5)
    judge = MockAdvisoryJudge(findings=[tier5])
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert result.record.advisories == [], "tier 5 must not fire without a task"

    # same finding WITH a task fires (fresh judge; edit shifts the cache hash)
    diff_repo.write("svc.py", "def add(a, b):\n    return int(a) + int(b)  # v3\n")
    judge2 = MockAdvisoryJudge(findings=[tier5])
    result2 = _pass_gate(
        diff_repo, scrubbed_env, advisory_judge=judge2, task_ref="add rate limiting"
    )
    assert len(result2.record.advisories) == 1
    assert result2.record.advisories[0]["tier"] == 5


def test_tier_mute_in_config(diff_repo, scrubbed_env):
    diff_repo.write(".proofjury.toml", "[advisory]\ntiers = [4]\n")
    judge = MockAdvisoryJudge(
        findings=[
            _finding(concern="tier four", tier=4),
            _finding(concern="tier five", tier=5),
        ]
    )
    result = _pass_gate(
        diff_repo, scrubbed_env, advisory_judge=judge, task_ref="the task"
    )
    assert [e["tier"] for e in result.record.advisories] == [4]


def test_max_findings_cap(diff_repo, scrubbed_env):
    diff_repo.write(".proofjury.toml", "[advisory]\nmax_findings = 2\n")
    judge = MockAdvisoryJudge(
        findings=[_finding(concern=f"finding {i}", target=f"f{i}.py:1") for i in range(5)]
    )
    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=judge)
    assert len(result.record.advisories) == 2


def test_advisory_content_is_scrubbed(diff_repo, scrubbed_env):
    env = dict(scrubbed_env, DEPLOY_TOKEN="supersecretvalue123")
    judge = MockAdvisoryJudge(
        findings=[_finding(concern="hardcoded supersecretvalue123 in the diff")]
    )
    result = _pass_gate(diff_repo, env, advisory_judge=judge)
    entry = result.record.advisories[0]
    assert "supersecretvalue123" not in entry["concern"]
    assert "[REDACTED]" in entry["concern"]
    assert "supersecretvalue123" not in result.record.advisory_output
    assert all("supersecretvalue123" not in n for n in result.agent_notes)


def test_broken_advisory_judge_never_breaks_the_gate(diff_repo, scrubbed_env):
    class ExplodingJudge:
        def review(self, advisory_input):
            raise RuntimeError("boom")

    result = _pass_gate(diff_repo, scrubbed_env, advisory_judge=ExplodingJudge())
    assert result.exit_code == 0
    assert result.record.advisories == []
    assert result.record.advisory_input == ""
    assert result.record.advisory_output == ""


# ---------------------------------------------------------------------------
# provider adapter (OpenRouter wire; OpenAI/Anthropic share the transports)
# ---------------------------------------------------------------------------


def _advisory_input(priors=None):
    return AdvisoryInput(
        action="deploy",
        repo_id="demo-app",
        task_ref=None,
        git_summary="branch main @ abc1234 (dirty)",
        results=[],
        priors=priors or [],
    )


def test_openrouter_advisory_success_parses_and_ledgers(tmp_path, record_factory):
    reply = {
        "model": "openai/gpt-4o-mini",
        "usage": {"cost": 0.0003},
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "findings": [
                                {
                                    "concern": "no retry on the webhook POST",
                                    "kind": "adjudication",
                                    "tier": 4,
                                    "confidence": 0.8,
                                    "grounded_in": ["chk_001", "chk_777"],
                                    "target": "notifications.py:12",
                                }
                            ]
                        }
                    )
                }
            }
        ],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=reply))
    judge = OpenRouterAdvisoryJudge(api_key="k", transport=transport, root=tmp_path)
    output = judge.review(_advisory_input(priors=[record_factory("chk_001")]))
    assert output.model_id == "openai/gpt-4o-mini"
    assert output.cost_usd == 0.0003
    assert len(output.findings) == 1
    assert output.findings[0].grounded_in == ["chk_001"]  # chk_777 not offered
    ledger = (tmp_path / "ledger.jsonl").read_text().strip().splitlines()
    assert json.loads(ledger[0])["cost_usd"] == 0.0003


def test_openrouter_advisory_error_yields_zero_findings(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    judge = OpenRouterAdvisoryJudge(api_key="k", transport=transport, root=tmp_path)
    output = judge.review(_advisory_input())
    assert output.findings == []
    assert output.model_id == "none"
    assert output.raw == ""


def test_advisory_prompt_contains_the_essentials(record_factory):
    prior = record_factory(
        "chk_003", resolution={"status": "false_positive", "at": "2026-07-01T00:00:00Z"}
    )
    advisory_input = AdvisoryInput(
        action="deploy",
        repo_id="demo-app",
        task_ref="add rate limiting",
        git_summary="the summary",
        results=[],
        priors=[prior],
        rejected_concerns=["old rejected concern"],
    )
    text = advisory_input.to_prompt_text()
    assert "Task: add rate limiting" in text
    assert "chk_003" in text and "resolution=false_positive" in text
    assert "do NOT re-raise" in text
    assert "old rejected concern" in text
    # no task → the prompt says so
    advisory_input.task_ref = None
    assert "do not emit tier-5" in advisory_input.to_prompt_text()

"""Advisory delivery through the agent hooks.

The channel invariant: advisory findings only ever ADD context. A passing
gate with agent-notes returns ``additionalContext`` with NO permission
decision; a blocked gate appends them to the deny reason; no path ever
emits an approval.
"""

import pytest

import proofjury.gate as gate_module
from proofjury.hooks import (
    ADVISORY_CONTEXT_HEADER,
    FINAL_INSTRUCTION,
    handle_cursor_hook,
    handle_hook,
)
from proofjury.judge.advisory import AdvisoryFinding
from proofjury.judge.advisory_mock import MockAdvisoryJudge
from proofjury.memory.store import MemoryStore
from proofjury.session import stamp

NO_DECISION: dict = {}

DEPLOY = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}


def _store(root):
    return MemoryStore(root / ".proofjury")


def _finding(concern="the webhook send has no retry", confidence=0.9):
    return AdvisoryFinding(
        concern=concern,
        kind="discovery",
        tier=4,
        confidence=confidence,
        grounded_in=[],
        target="notifications.py:12",
    )


@pytest.fixture
def advisory_judge(monkeypatch):
    """Route the gate's advisory judge selection to a mock (the hook path
    offers no injection seam — selection is env-driven in production)."""

    def _install(findings):
        judge = MockAdvisoryJudge(findings=findings)
        monkeypatch.setattr(
            gate_module, "get_advisory_judge", lambda env, root, config: judge
        )
        return judge

    return _install


@pytest.fixture
def passing_diff_repo(tmp_repo):
    """Passing gate + a non-trivial diff (the advisory entry condition)."""
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("svc.py", "def add(a, b):\n    return int(a) + int(b)\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest", "-q"])
    return tmp_repo


@pytest.fixture
def failing_diff_repo(tmp_repo):
    """Blocked gate (missing env var, tests not run) + a non-trivial diff."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n# v2\n')
    return tmp_repo


def test_passing_gate_injected_advisory_becomes_additional_context(
    passing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.9)])
    output = handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env)
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in hso, "context must never carry a decision"
    assert "permissionDecisionReason" not in hso
    assert hso["additionalContext"].startswith(ADVISORY_CONTEXT_HEADER)
    assert "no retry" in hso["additionalContext"]
    record = _store(passing_diff_repo.root).get("chk_001")
    assert record.gate_passed
    assert record.advisories[0]["delivery"] == "injected"


def test_passing_gate_held_advisory_stays_invisible_to_agent(
    passing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.5)])
    output = handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env)
    assert output == NO_DECISION, "held findings must not reach the agent"
    record = _store(passing_diff_repo.root).get("chk_001")
    assert record.advisories[0]["delivery"] == "held"


def test_blocked_gate_appends_advisory_to_deny_reason(
    failing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.9)])
    output = handle_hook(DEPLOY, failing_diff_repo.root, scrubbed_env)
    hso = output["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny", "the block itself is unchanged"
    reason = hso["permissionDecisionReason"]
    assert "Failed checks:" in reason
    assert ADVISORY_CONTEXT_HEADER in reason
    assert "no retry" in reason
    assert reason.endswith(FINAL_INSTRUCTION)


def test_approved_advisory_delivered_on_next_event(
    passing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.5)])
    assert handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env) == NO_DECISION
    store = _store(passing_diff_repo.root)
    # human approves out-of-band
    assert store.label_advisory("chk_001", 0, delivery="staged")
    output = handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "human-approved advisory chk_001#0" in context
    assert "permissionDecision" not in output["hookSpecificOutput"]
    assert store.get("chk_001").advisories[0]["delivery"] == "sent"
    # delivered once — the event after that is silent again
    assert handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env) == NO_DECISION


def test_rejected_injected_advisory_retracted_on_next_event(
    passing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.9)])
    first = handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env)
    assert "additionalContext" in first["hookSpecificOutput"]
    store = _store(passing_diff_repo.root)
    store.label_advisory("chk_001", 0, label="rejected", retraction="staged")
    output = handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Disregard advisory chk_001#0" in context
    assert "human reviewed and rejected" in context
    entry = store.get("chk_001").advisories[0]
    assert entry["retraction"] == "sent"
    assert handle_hook(DEPLOY, passing_diff_repo.root, scrubbed_env) == NO_DECISION


def test_cursor_passing_gate_notes_carry_no_permission_key(
    passing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.9)])
    output = handle_cursor_hook(
        {"command": "./deploy.sh"}, passing_diff_repo.root, scrubbed_env
    )
    assert "permission" not in output, "context must never set a permission"
    assert output["agent_message"].startswith(ADVISORY_CONTEXT_HEADER)
    assert "no retry" in output["agent_message"]


def test_cursor_blocked_gate_deny_includes_advisory(
    failing_diff_repo, scrubbed_env, advisory_judge
):
    advisory_judge([_finding(confidence=0.9)])
    output = handle_cursor_hook(
        {"command": "./deploy.sh"}, failing_diff_repo.root, scrubbed_env
    )
    assert output["permission"] == "deny"
    assert ADVISORY_CONTEXT_HEADER in output["agent_message"]

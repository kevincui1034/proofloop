"""Gate orchestration invariants — the product's core guarantees."""

import io
import json
import sys

import pytest
from rich.console import Console
from typer.testing import CliRunner

import proofloop.cli as cli_module
from proofloop.cli import app
from proofloop.gate import run_gate, scrub_text
from proofloop.judge import DeterministicJudge
from proofloop.memory.store import MemoryStore
from proofloop.session import stamp

runner = CliRunner()


def _sentinel_cmd(path):
    return [sys.executable, "-c", f"open({str(path)!r}, 'w').write('ran')"]


def _store(root):
    return MemoryStore(root / ".proofloop")


@pytest.fixture
def failing_repo(tmp_repo):
    """A repo that fails missing_env_var (and tests_not_run)."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    return tmp_repo


@pytest.fixture
def passing_repo(tmp_repo, scrubbed_env):
    """A repo with zero failures: no env reads, tests stamped fresh."""
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest", "-q"])
    return tmp_repo


def test_blocked_run_never_spawns_child(failing_repo, scrubbed_env, tmp_path_factory):
    sentinel = tmp_path_factory.mktemp("outside") / "deployed.txt"
    result = run_gate(
        failing_repo.root,
        "deploy",
        _sentinel_cmd(sentinel),
        env=scrubbed_env,
        render=False,
    )
    assert result.blocked
    assert result.exit_code == 2
    assert not sentinel.exists(), "BLOCKED gate must never spawn the command"
    record = result.record
    assert record.gate_passed is False
    assert "missing_env_var" in record.failure_classes()


def test_pass_executes_child_and_propagates_zero(passing_repo, scrubbed_env, tmp_path_factory):
    sentinel = tmp_path_factory.mktemp("outside") / "deployed.txt"
    result = run_gate(
        passing_repo.root,
        "deploy",
        _sentinel_cmd(sentinel),
        env=scrubbed_env,
        render=False,
    )
    assert not result.blocked
    assert result.exit_code == 0
    assert sentinel.exists()
    assert result.record.gate_passed is True


def test_pass_propagates_child_exit_code(passing_repo, scrubbed_env):
    result = run_gate(
        passing_repo.root,
        "deploy",
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        env=scrubbed_env,
        render=False,
    )
    assert result.exit_code == 7


def test_no_exec_passes_without_spawning(passing_repo, scrubbed_env, tmp_path_factory):
    sentinel = tmp_path_factory.mktemp("outside") / "deployed.txt"
    result = run_gate(
        passing_repo.root,
        "deploy",
        _sentinel_cmd(sentinel),
        no_exec=True,
        env=scrubbed_env,
        render=False,
    )
    assert result.exit_code == 0
    assert not sentinel.exists()


def test_force_runs_child_and_logs_override(failing_repo, scrubbed_env, tmp_path_factory):
    sentinel = tmp_path_factory.mktemp("outside") / "deployed.txt"
    result = run_gate(
        failing_repo.root,
        "deploy",
        _sentinel_cmd(sentinel),
        force=True,
        env=scrubbed_env,
        render=False,
    )
    assert not result.blocked
    assert result.exit_code == 0
    assert sentinel.exists()
    assert result.record.gate_passed is False
    assert result.record.resolution["status"] == "overridden"


def test_every_run_appends_a_record(failing_repo, scrubbed_env):
    run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    records = list(_store(failing_repo.root).iter_records())
    assert len(records) == 2
    assert [r.id for r in records] == ["chk_001", "chk_002"]
    assert (failing_repo.root / ".proofloop" / "memory.md").exists()


def test_recurrence_sets_recalled_from(failing_repo, scrubbed_env):
    first = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    second = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    assert first.record.recalled_from is None
    assert second.record.recalled_from == first.record.id


def test_auto_resolution_links_fix_to_failure(failing_repo, scrubbed_env):
    blocked = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    assert blocked.blocked
    # Fix: provide the env var and run tests against this worktree.
    fixed_env = dict(scrubbed_env, STRIPE_API_KEY="sk_test_x")
    stamp(failing_repo.root, "tests", 0, ["pytest"])
    passed = run_gate(failing_repo.root, "deploy", ["true"], env=fixed_env, render=False)
    assert passed.record.gate_passed
    assert passed.record.resolves == blocked.record.id
    prior = _store(failing_repo.root).get(blocked.record.id)
    assert prior.resolution["status"] == "auto_resolved"
    assert prior.resolution["resolved_by"] == passed.record.id


def test_proof_files_written_under_context_ref(failing_repo, scrubbed_env):
    result = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    run_dir = failing_repo.root / ".proofloop" / "runs" / result.record.id
    for ref in result.record.proof_refs:
        assert (run_dir / ref).exists()
    checks = json.loads((run_dir / "checks.json").read_text())
    assert any(c["name"] == "env_vars" and not c["passed"] for c in checks)


def test_env_values_scrubbed_from_persisted_record(tmp_repo, scrubbed_env):
    secret_value = "super-secret-value-42"
    tmp_repo.write("tracked.py", "x = 1\n")
    tmp_repo.git("add", "tracked.py")
    tmp_repo.git("commit", "-qm", "init")
    # The secret value now appears in the git diff the gate captures.
    tmp_repo.write("tracked.py", f'x = "{secret_value}"\n')
    env = dict(scrubbed_env, MY_TOKEN=secret_value)
    result = run_gate(tmp_repo.root, "deploy", ["true"], env=env, render=False)
    serialized = json.dumps(result.record.to_dict())
    assert secret_value not in serialized
    assert "[REDACTED]" in result.record.judge_input
    proof_dir = tmp_repo.root / ".proofloop" / "runs" / result.record.id
    assert secret_value not in (proof_dir / "diff.patch").read_text()


def test_scrub_text_unit(scrubbed_env):
    env = dict(scrubbed_env, TOKEN="abcdefgh12345678", SHORT="tiny")
    assert scrub_text("x abcdefgh12345678 y", env) == "x [REDACTED] y"
    assert scrub_text("tiny stays", env) == "tiny stays"  # < 8 chars: kept


def test_env_fingerprint_is_names_only(failing_repo, scrubbed_env):
    env = dict(scrubbed_env, STRIPE_API_KEY="sk_test_secretvalue")
    result = run_gate(failing_repo.root, "deploy", ["true"], env=env, render=False)
    assert "STRIPE_API_KEY" in result.record.env_fingerprint
    assert all("secretvalue" not in name for name in result.record.env_fingerprint)


def test_guard_cli_json_output(failing_repo, monkeypatch):
    monkeypatch.chdir(failing_repo.root)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    result = runner.invoke(app, ["guard", "deploy", "--json", "--", "true"])
    assert result.exit_code == 2
    record = json.loads(result.stdout.strip().splitlines()[-1])
    assert record["gate_passed"] is False
    assert record["id"] == "chk_001"


def test_guard_cli_internal_error_exits_3(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_module, "run_gate", boom)
    result = runner.invoke(app, ["guard", "deploy", "--", "true"])
    assert result.exit_code == 3


def test_guard_cli_requires_command(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["guard", "deploy"])
    assert result.exit_code == 64  # EX_USAGE — never collides with BLOCKED (2)


# --------------------------------------------------------------------------
# usage errors (EX_USAGE = 64) and the missing `--` sentinel
# --------------------------------------------------------------------------


def test_guard_without_sentinel_is_usage_error(failing_repo, monkeypatch):
    """`proofloop guard deploy vercel --force` must not consume --force as
    guard's own flag (self-force-override) — it exits 64 with guidance."""
    monkeypatch.chdir(failing_repo.root)
    result = runner.invoke(app, ["guard", "deploy", "vercel", "--force"])
    assert result.exit_code == 64
    # the gate never ran: no record was written
    assert not (failing_repo.root / ".proofloop" / "memory.jsonl").exists()


def test_run_without_sentinel_is_usage_error(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["run", "tests", "pytest", "-q"])
    assert result.exit_code == 64
    assert not (tmp_repo.root / ".proofloop" / "session.json").exists()


def test_run_unknown_kind_is_usage_error(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["run", "nope", "--", "true"])
    assert result.exit_code == 64


def test_guard_with_sentinel_keeps_wrapped_flags(failing_repo, monkeypatch):
    """After ` -- `, the wrapped command's --force belongs to the command,
    not to guard: the gate still blocks (exit 2, not forced)."""
    monkeypatch.chdir(failing_repo.root)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    result = runner.invoke(app, ["guard", "deploy", "--", "vercel", "--force"])
    assert result.exit_code == 2


# --------------------------------------------------------------------------
# child exit codes: 127 / 126 / signals (fixes for exit-code collisions)
# --------------------------------------------------------------------------


def test_missing_child_after_pass_exits_127(passing_repo, scrubbed_env):
    result = run_gate(
        passing_repo.root,
        "deploy",
        ["/definitely/not/a/real/cmd-xyz"],
        env=scrubbed_env,
        render=False,
    )
    assert result.record.gate_passed
    assert result.exit_code == 127


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX exec-bit / 126 convention; Windows raises WinError 193 instead",
)
def test_non_executable_child_after_pass_exits_126(passing_repo, scrubbed_env):
    script = passing_repo.root / "not-executable.sh"
    script.write_text("#!/bin/sh\necho hi\n")  # no +x bit
    stamp(passing_repo.root, "tests", 0, ["pytest", "-q"])  # re-bind digest
    result = run_gate(
        passing_repo.root, "deploy", [str(script)], env=scrubbed_env, render=False
    )
    assert result.record.gate_passed
    assert result.exit_code == 126


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX signal semantics (SIGTERM → 143); no equivalent on Windows",
)
def test_signal_killed_child_maps_to_128_plus_signal(passing_repo, scrubbed_env):
    result = run_gate(
        passing_repo.root,
        "deploy",
        [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
        env=scrubbed_env,
        render=False,
    )
    assert result.exit_code == 128 + 15  # SIGTERM → 143, not 241


# --------------------------------------------------------------------------
# run: persisted logs and session cmd are scrubbed
# --------------------------------------------------------------------------


def test_run_log_and_session_cmd_scrubbed(tmp_repo, monkeypatch):
    secret = "super-secret-value-42"
    monkeypatch.chdir(tmp_repo.root)
    monkeypatch.setenv("MY_TOKEN", secret)
    code = f"print({secret!r})"
    result = runner.invoke(app, ["run", "tests", "--", sys.executable, "-c", code])
    assert result.exit_code == 0
    logs = list((tmp_repo.root / ".proofloop" / "runs").glob("tests-*.log"))
    assert len(logs) == 1
    log_text = logs[0].read_text()
    assert secret not in log_text
    assert "[REDACTED]" in log_text
    session = json.loads((tmp_repo.root / ".proofloop" / "session.json").read_text())
    stored_cmd = json.dumps(session["tests"]["cmd"])
    assert secret not in stored_cmd
    assert "[REDACTED]" in stored_cmd


# --------------------------------------------------------------------------
# scrub: JSON-escaped env values must not survive in proof files
# --------------------------------------------------------------------------


def test_scrub_text_matches_json_escaped_form(scrubbed_env):
    nasty = 'ab"cd\nef!!'  # 10 chars, with a quote and a newline
    env = dict(scrubbed_env, TOKEN=nasty)
    serialized = json.dumps({"x": nasty})
    scrubbed = json.dumps(json.loads(scrub_text(serialized, env)))
    assert "REDACTED" in scrubbed
    assert "cd\\nef" not in scrubbed
    assert scrub_text(nasty, env) == "[REDACTED]"


def test_proof_context_json_scrubs_escaped_env_values(tmp_repo, scrubbed_env):
    secret = 'top"secret\nvalue!'
    env = dict(scrubbed_env, NASTY_TOKEN=secret)
    result = run_gate(
        tmp_repo.root, "deploy", ["echo", secret], no_exec=True, env=env, render=False
    )
    ctx_path = tmp_repo.root / ".proofloop" / "runs" / result.record.id / "context.json"
    ctx_text = ctx_path.read_text()
    escaped = json.dumps(secret)[1:-1]  # the JSON-escaped form
    assert secret not in ctx_text
    assert escaped not in ctx_text
    assert json.loads(ctx_text)["cmd"] == ["echo", "[REDACTED]"]


# --------------------------------------------------------------------------
# auto-resolution closes ALL open priors, not just the latest
# --------------------------------------------------------------------------


def test_auto_resolution_resolves_all_open_priors(failing_repo, scrubbed_env):
    first = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    second = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    assert first.blocked and second.blocked
    fixed_env = dict(scrubbed_env, STRIPE_API_KEY="sk_test_x")
    stamp(failing_repo.root, "tests", 0, ["pytest"])
    passed = run_gate(failing_repo.root, "deploy", ["true"], env=fixed_env, render=False)
    assert passed.record.gate_passed
    assert passed.record.resolves == second.record.id  # cites the most recent
    store = _store(failing_repo.root)
    for rec in (first.record, second.record):
        prior = store.get(rec.id)
        assert prior.resolution["status"] == "auto_resolved"
        assert prior.resolution["resolved_by"] == passed.record.id


# --------------------------------------------------------------------------
# repo identity survives remote changes (persisted .proofloop/repo_id)
# --------------------------------------------------------------------------


def test_repo_id_persisted_across_remote_changes(failing_repo, scrubbed_env):
    first = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    id_file = failing_repo.root / ".proofloop" / "repo_id"
    assert id_file.read_text().strip() == first.record.repo_id
    # adding an origin remote would change the derived id …
    failing_repo.git("remote", "add", "origin", "git@github.com:acme/renamed.git")
    second = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    # … but the persisted id keeps prior records reachable for recall
    assert second.record.repo_id == first.record.repo_id
    assert second.record.recalled_from == first.record.id


# --------------------------------------------------------------------------
# recall short-circuit: a strong recurrence never calls the LLM engine
# --------------------------------------------------------------------------


def test_strong_recall_skips_llm_engine(failing_repo, scrubbed_env, monkeypatch):
    import proofloop.gate as gate_module
    from proofloop.judge import MockJudge

    first = run_gate(failing_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)

    spy = MockJudge()
    factory_calls = []

    def fake_get_judge(env, root=None):
        factory_calls.append(env)
        return spy

    monkeypatch.setattr(gate_module, "get_judge", fake_get_judge)
    llm_env = dict(scrubbed_env, OPENROUTER_API_KEY="k")  # LLM configured …
    second = run_gate(failing_repo.root, "deploy", ["true"], env=llm_env, render=False)
    assert second.record.recalled_from == first.record.id
    assert factory_calls == [] and spy.calls == []  # … but never consulted
    assert second.record.judge_model_id == "deterministic/proofloop-v1"
    assert second.record.diagnosis.startswith(f"Seen before — matches {first.record.id}")


def test_engine_consulted_without_strong_recall(failing_repo, scrubbed_env, monkeypatch):
    import proofloop.gate as gate_module
    from proofloop.judge import MockJudge

    spy = MockJudge()
    monkeypatch.setattr(gate_module, "get_judge", lambda env, root=None: spy)
    llm_env = dict(scrubbed_env, OPENROUTER_API_KEY="k")
    result = run_gate(failing_repo.root, "deploy", ["true"], env=llm_env, render=False)
    assert result.blocked
    assert len(spy.calls) == 1  # first occurrence: the engine explains


# --------------------------------------------------------------------------
# discoverability hint: nudge to `proofloop login` only when blocked with a
# deterministic diagnosis and no LLM configured
# --------------------------------------------------------------------------

LOGIN_HINT = "proofloop login"


def _render(root, env, judge=None):
    buf = io.StringIO()
    con = Console(file=buf, width=120, highlight=False, no_color=True)
    run_gate(root, "deploy", ["true"], env=env, render=True, console=con, judge=judge)
    return buf.getvalue()


def test_blocked_deterministic_without_llm_shows_login_hint(failing_repo, scrubbed_env):
    out = _render(failing_repo.root, scrubbed_env, judge=DeterministicJudge())
    assert LOGIN_HINT in out


def test_blocked_hint_suppressed_when_llm_configured(failing_repo, scrubbed_env):
    env = dict(scrubbed_env, ANTHROPIC_API_KEY="k")  # llm_configured → True
    out = _render(failing_repo.root, env, judge=DeterministicJudge())
    assert LOGIN_HINT not in out


def test_allowed_run_never_shows_login_hint(passing_repo, scrubbed_env):
    out = _render(passing_repo.root, scrubbed_env, judge=DeterministicJudge())
    assert LOGIN_HINT not in out

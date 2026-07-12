"""Cross-repo memory recall — priors from other repos on this machine.

Foreign priors are context, never the decision: they sort below every
same-repo prior, never trigger the deterministic strong-match
short-circuit, and never change pass/fail or the exit code.
"""

import json
import os
import subprocess

import pytest
from rich.console import Console

from proofjury.gate import run_gate
from proofjury.memory.recall import is_foreign_prior, recall
from proofjury.memory.registry import load_registry
from proofjury.memory.store import MemoryStore
from proofjury.checks.base import CheckResult, Evidence


def _failure(name="STRIPE_API_KEY"):
    return CheckResult(
        name="env_vars",
        passed=False,
        failure_class="missing_env_var",
        evidence=[Evidence(file="payments.py", line=14, detail=name)],
        evidence_suffix="unset",
        fix_hint=f"export {name}",
    )


def _git_init(root):
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@proofjury.local"],
        ["config", "user.name", "proofjury-tests"],
    ):
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def _make_repo(tmp_path_factory, name):
    root = tmp_path_factory.mktemp(name)
    _git_init(root)
    (root / "payments.py").write_text(
        'import os\nKEY = os.environ["STRIPE_API_KEY"]\n'
    )
    return root


@pytest.fixture
def repo_a(tmp_path_factory):
    """A repo that fails missing_env_var (and tests_not_run)."""
    return _make_repo(tmp_path_factory, "repo-a")


@pytest.fixture
def repo_b(tmp_path_factory):
    """A second repo, distinct root (and therefore distinct repo_id)."""
    return _make_repo(tmp_path_factory, "repo-b")


# -- recall() unit level -------------------------------------------------------


def test_foreign_prior_recalled_with_qualified_id(tmp_path, record_factory):
    local = MemoryStore(tmp_path / "local" / ".proofjury")
    other = MemoryStore(tmp_path / "other" / ".proofjury")
    other.append(record_factory("chk_007", repo_id="repo-b"))
    priors = recall(local, "repo-a", [_failure()], foreign=[("repo-b", other)])
    assert [p.id for p in priors] == ["repo-b:chk_007"]
    assert is_foreign_prior(priors[0])


def test_local_prior_always_outranks_foreign(tmp_path, record_factory):
    local = MemoryStore(tmp_path / "local" / ".proofjury")
    other = MemoryStore(tmp_path / "other" / ".proofjury")
    # Local prior: zero token overlap (different env var), old.
    local.append(
        record_factory(
            "chk_001",
            repo_id="repo-a",
            created_at="2020-01-01T00:00:00Z",
            checks=[
                {
                    "name": "env_vars",
                    "type": "deterministic",
                    "passed": False,
                    "failure_class": "missing_env_var",
                    "evidence": "OTHER_VAR (app.py:1) unset",
                }
            ],
        )
    )
    # Foreign prior: exact evidence match, recent — still sorts below.
    other.append(record_factory("chk_009", repo_id="repo-b", created_at="2026-07-01T00:00:00Z"))
    priors = recall(local, "repo-a", [_failure()], foreign=[("repo-b", other)])
    assert [p.id for p in priors] == ["chk_001", "repo-b:chk_009"]
    assert not is_foreign_prior(priors[0])


def test_foreign_false_positive_excluded(tmp_path, record_factory):
    local = MemoryStore(tmp_path / "local" / ".proofjury")
    other = MemoryStore(tmp_path / "other" / ".proofjury")
    other.append(
        record_factory(
            "chk_003",
            repo_id="repo-b",
            resolution={"status": "false_positive", "note": "", "at": ""},
        )
    )
    assert recall(local, "repo-a", [_failure()], foreign=[("repo-b", other)]) == []


def test_corrupt_foreign_store_never_poisons_recall(tmp_path, record_factory):
    local = MemoryStore(tmp_path / "local" / ".proofjury")
    local.append(record_factory("chk_001", repo_id="repo-a"))
    broken_root = tmp_path / "broken" / ".proofjury"
    broken_root.mkdir(parents=True)
    (broken_root / "memory.jsonl").write_text('{"id": "chk_x"}\nnot json at all\n')
    priors = recall(
        local, "repo-a", [_failure()], foreign=[("broken", MemoryStore(broken_root))]
    )
    assert [p.id for p in priors] == ["chk_001"]


def test_no_foreign_arg_is_todays_behavior(tmp_path, record_factory):
    local = MemoryStore(tmp_path / "local" / ".proofjury")
    local.append(record_factory("chk_001", repo_id="repo-a"))
    assert [p.id for p in recall(local, "repo-a", [_failure()])] == ["chk_001"]


# -- gate end-to-end -----------------------------------------------------------


def _block(root, env):
    return run_gate(root, "deploy", ["true"], env=env, render=False)


def test_gate_recalls_across_repos(repo_a, repo_b, scrubbed_env):
    first = _block(repo_a, scrubbed_env)
    assert first.blocked and first.record.recalled_from is None

    second = _block(repo_b, scrubbed_env)
    assert second.blocked and second.exit_code == 2
    repo_a_id = first.record.repo_id
    assert second.record.recalled_from == f"{repo_a_id}:{first.record.id}"


def test_foreign_prior_never_strong_matches(repo_a, repo_b, scrubbed_env):
    """A byte-identical foreign failure must NOT short-circuit the judge."""
    from proofjury.judge import MockJudge

    _block(repo_a, scrubbed_env)
    spy = MockJudge()
    result = run_gate(repo_b, "deploy", ["true"], env=scrubbed_env, render=False, judge=spy)
    assert result.blocked
    assert len(spy.calls) == 1  # configured judge consulted, not DeterministicJudge
    assert ":" in (result.record.recalled_from or "")


def test_deterministic_judge_names_the_foreign_repo(repo_a, repo_b, scrubbed_env):
    first = _block(repo_a, scrubbed_env)
    con = Console(file=__import__("io").StringIO(), width=100, force_terminal=False)
    run_gate(repo_b, "deploy", ["true"], env=scrubbed_env, render=True, console=con)
    out = con.file.getvalue()
    repo_a_id = first.record.repo_id
    assert f"Seen before in {repo_a_id}" in out
    assert f"seen before in {repo_a_id}" in out  # the recalled panel line


def test_config_kill_switch_disables_and_deregisters(repo_a, repo_b, scrubbed_env):
    _block(repo_a, scrubbed_env)
    (repo_b / ".proofjury.toml").write_text("[memory]\ncross_repo = false\n")
    result = _block(repo_b, scrubbed_env)
    assert result.blocked
    assert result.record.recalled_from is None
    registered = load_registry(scrubbed_env)["repos"]
    assert str((repo_b / ".proofjury").resolve()) not in registered
    assert str((repo_a / ".proofjury").resolve()) in registered


def test_env_kill_switch_disables(repo_a, repo_b, scrubbed_env):
    _block(repo_a, scrubbed_env)
    env = dict(scrubbed_env, PROOFJURY_NO_CROSS_REPO="1")
    result = _block(repo_b, env)
    assert result.record.recalled_from is None
    assert str((repo_b / ".proofjury").resolve()) not in load_registry(env)["repos"]


def test_local_prior_still_wins_recalled_from(repo_a, repo_b, scrubbed_env):
    _block(repo_b, scrubbed_env)  # foreign candidate
    first_local = _block(repo_a, scrubbed_env)
    second_local = _block(repo_a, scrubbed_env)
    # Same-repo prior outranks the foreign one: bare id, not qualified.
    assert second_local.record.recalled_from == first_local.record.id


# -- stats ----------------------------------------------------------------------


def test_stats_count_cross_repo(repo_a, repo_b, scrubbed_env):
    from proofjury.memory.export import stats

    _block(repo_a, scrubbed_env)
    _block(repo_b, scrubbed_env)
    store_b = MemoryStore(repo_b / ".proofjury")
    data = stats(store_b, store_b.root / "ledger.jsonl", env=scrubbed_env)
    assert data["cross_repo"] == {"registered_repos": 2, "recall_hits": 1}


def test_memory_stats_json_exposes_cross_repo(repo_a, repo_b, scrubbed_env, monkeypatch):
    from typer.testing import CliRunner

    from proofjury.cli import app

    # Align the gate's registry env with what the CLI will read (os.environ,
    # whose HOME the autouse fixture already points at a per-test tmp dir).
    env = {"HOME": os.environ["HOME"], "PATH": scrubbed_env["PATH"]}
    _block(repo_a, env)
    _block(repo_b, env)
    monkeypatch.chdir(repo_b)
    result = CliRunner().invoke(app, ["memory", "stats", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["cross_repo"]["registered_repos"] == 2
    assert data["cross_repo"]["recall_hits"] == 1


def test_memory_repos_lists_registered_stores(repo_a, repo_b, scrubbed_env, monkeypatch):
    from typer.testing import CliRunner

    from proofjury.cli import app

    env = {"HOME": os.environ["HOME"], "PATH": scrubbed_env["PATH"]}
    _block(repo_a, env)
    _block(repo_b, env)
    monkeypatch.chdir(repo_b)
    result = CliRunner().invoke(app, ["memory", "repos"])
    assert result.exit_code == 0
    assert "present" in result.output

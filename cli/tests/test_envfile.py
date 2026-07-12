"""Deploy-env fidelity: env-file parsing + the three-envs separation.

Checks evaluate against the deploy target's env (--env-file / [env].file),
the child spawns with the developer's real env, and persisted output is
scrubbed against the UNION of both.
"""

import json

import pytest
from typer.testing import CliRunner

from proofjury.cli import app
from proofjury.envfile import parse_env_file
from proofjury.gate import run_gate

runner = CliRunner()


# -- parser --------------------------------------------------------------


def test_parse_env_file_basics(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment line\n"
        "\n"
        "PLAIN=value\n"
        "export EXPORTED=yes\n"
        'DOUBLE="quoted value"\n'
        "SINGLE='single quoted'\n"
        "NO_INTERP=$HOME/literal\n"
        "EMPTY=\n"
        "not a valid line\n"
    )
    parsed = parse_env_file(path)
    assert parsed == {
        "PLAIN": "value",
        "EXPORTED": "yes",
        "DOUBLE": "quoted value",
        "SINGLE": "single quoted",
        "NO_INTERP": "$HOME/literal",  # no interpolation, ever
        "EMPTY": "",
    }


def test_parse_env_file_missing_raises(tmp_path):
    with pytest.raises(OSError):
        parse_env_file(tmp_path / "nope.env")


# -- guard --env-file ------------------------------------------------------


def test_env_file_overrides_process_env_for_checks(tmp_repo, scrubbed_env):
    """A var set in the developer's shell but absent from the env file is a
    missing_env_var — the check sees the deploy target's env, not the shell."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    env_file = tmp_repo.write("env.production", "OTHER_VAR=present\n")
    dev_env = {**scrubbed_env, "STRIPE_API_KEY": "sk_live_1234567890abcdef"}
    result = run_gate(
        tmp_repo.root,
        "deploy",
        None,
        no_exec=True,
        env=dev_env,
        deploy_env=parse_env_file(env_file),
        render=False,
    )
    assert result.blocked
    failed = [r for r in result.failures if r.failure_class == "missing_env_var"]
    assert failed and "STRIPE_API_KEY" in failed[0].evidence_str()


def test_no_env_file_keeps_todays_behavior(tmp_repo, scrubbed_env):
    """Regression guard: deploy_env=None → checks see the process env."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    dev_env = {**scrubbed_env, "STRIPE_API_KEY": "sk_live_1234567890abcdef"}
    result = run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=dev_env, render=False
    )
    assert not any(r.failure_class == "missing_env_var" for r in result.failures)


def test_env_file_values_scrubbed(tmp_repo, scrubbed_env):
    """Env-file values are deploy secrets: they must appear nowhere in
    persisted output, even when the worktree diff contains them."""
    secret = "whsec_deploy_secret_value_123456"
    tmp_repo.write("app.py", "x = 1\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("app.py", f'x = 1\ntoken = "{secret}"\n')  # secret enters the diff
    env_file = tmp_repo.write("env.production", f"WEBHOOK_SECRET={secret}\n")
    run_gate(
        tmp_repo.root,
        "deploy",
        None,
        no_exec=True,
        env=dict(scrubbed_env),
        deploy_env=parse_env_file(env_file),
        render=False,
    )
    proof_root = tmp_repo.root / ".proofjury"
    for path in proof_root.rglob("*"):
        if path.is_file():
            assert secret not in path.read_text(errors="ignore"), path


def test_env_fingerprint_uses_deploy_env_names(tmp_repo, scrubbed_env):
    env_file = tmp_repo.write("env.production", "A_VAR=1\nB_VAR=2\n")
    result = run_gate(
        tmp_repo.root,
        "deploy",
        None,
        no_exec=True,
        env=dict(scrubbed_env),
        deploy_env=parse_env_file(env_file),
        render=False,
    )
    assert result.record.env_fingerprint == ["A_VAR", "B_VAR"]


def test_missing_env_file_is_usage_error(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(
        app, ["guard", "deploy", "--no-exec", "--env-file", "nope.env"]
    )
    assert result.exit_code == 64  # EX_USAGE — never collides with BLOCKED (2)


def test_guard_env_file_cli_blocks_on_missing_var(tmp_repo, monkeypatch):
    """Acceptance: exported locally, absent from .env.production → exit 2."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.write(".env.production", "OTHER_VAR=present\n")
    monkeypatch.chdir(tmp_repo.root)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_1234567890abcdef")
    result = runner.invoke(
        app, ["guard", "deploy", "--no-exec", "--env-file", ".env.production"]
    )
    assert result.exit_code == 2
    assert "missing_env_var" in result.stdout
    assert "STRIPE_API_KEY" in result.stdout


# -- hook [env].file --------------------------------------------------------


def test_toml_env_file_used_by_hook(tmp_repo, scrubbed_env):
    from proofjury.hooks import handle_hook

    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.write(".proofjury.toml", '[env]\nfile = ".env.production"\n')
    tmp_repo.write(".env.production", "OTHER_VAR=present\n")
    hook_env = {**scrubbed_env, "STRIPE_API_KEY": "sk_live_1234567890abcdef"}
    payload = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    output = handle_hook(payload, tmp_repo.root, hook_env)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "STRIPE_API_KEY" in reason


def test_toml_env_file_unreadable_fails_closed(tmp_repo, monkeypatch):
    """A configured-but-unreadable [env].file must DENY (exit 2), never
    silently fall back to os.environ."""
    tmp_repo.write(".proofjury.toml", '[env]\nfile = ".env.production"\n')  # not created
    monkeypatch.chdir(tmp_repo.root)
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    )
    result = runner.invoke(app, ["hook"], input=payload)
    assert result.exit_code == 2
    output = json.loads(result.stdout.strip().splitlines()[-1])
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

"""Claude Code PreToolUse adapter: deny decisions + actionable payloads.

The hook must never auto-approve: everything except a deploy command
failing the gate returns {} (no decision), so Claude Code's normal
permission flow stays in charge.
"""

import json

from typer.testing import CliRunner

from proofloop.cli import app
from proofloop.hooks import (
    DEFAULT_DEPLOY_PATTERNS,
    FINAL_INSTRUCTION,
    compile_deploy_patterns,
    handle_hook,
    is_deploy_command,
    is_proofloop_invocation,
)
from proofloop.memory.store import MemoryStore
from proofloop.session import stamp

runner = CliRunner()

NO_DECISION: dict = {}


def _decision(output: dict) -> str:
    return output["hookSpecificOutput"]["permissionDecision"]

def _reason(output: dict) -> str:
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def test_default_patterns_match_deploy_commands():
    deploys = [
        "vercel --prod",
        "vercel deploy --prebuilt",
        "fly deploy",
        "railway up",
        "netlify deploy --prod",
        "git push origin production",
        "git push origin improve-production-docs",  # \bproduction\b — accepted
        "./deploy.sh",
        "./deploy",
        "bash deploy.sh --fast",
        "sh ./deploy.sh",
        "bash ../scripts/deploy.sh",
        "cd x && ./deploy.sh",
        "echo hi; ./deploy.sh",
        "true | bash scripts/deploy.sh",
    ]
    for command in deploys:
        assert is_deploy_command(command, DEFAULT_DEPLOY_PATTERNS), command


def test_default_patterns_ignore_normal_commands():
    normal = [
        "ls -la",
        "git push origin main",
        "npm test",
        "pytest -q",
        "cat deploy.md",
        # reading a deploy script is not deploying (invocation-anchored):
        "cat deploy.sh",
        "vim deploy.sh",
        "less ./deploy.sh",
        "grep -n foo deploy.sh",
        "ls ../deployments",
        # word boundaries on the git push branch pattern:
        "git push origin feature/reproduce-bug",
        "git push origin reproduce-fix",
        "git push origin prerelease",
    ]
    for command in normal:
        assert not is_deploy_command(command, DEFAULT_DEPLOY_PATTERNS), command


def test_non_deploy_command_gets_no_decision(tmp_repo, scrubbed_env):
    """No 'allow' for normal commands — that would bypass the permission
    system and auto-approve every Bash call."""
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    assert handle_hook(payload, tmp_repo.root, scrubbed_env) == NO_DECISION


def test_missing_command_gets_no_decision(tmp_repo, scrubbed_env):
    payload = {"tool_name": "Read", "tool_input": {}}
    assert handle_hook(payload, tmp_repo.root, scrubbed_env) == NO_DECISION


def test_malformed_but_parseable_input_gets_no_decision(tmp_repo, scrubbed_env):
    for payload in (
        {},
        {"tool_input": "not-a-dict"},
        {"tool_input": {"command": 42}},
        {"tool_input": {"command": "   "}},
        {"tool_input": ["list", "not", "dict"]},
    ):
        assert handle_hook(payload, tmp_repo.root, scrubbed_env) == NO_DECISION, payload


def test_deploy_with_failures_denied_with_structured_reason(tmp_repo, scrubbed_env):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    payload = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    output = handle_hook(payload, tmp_repo.root, scrubbed_env)
    assert _decision(output) == "deny"
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    reason = _reason(output)
    # Structured, agent-actionable payload:
    assert "Failed checks:" in reason
    assert "missing_env_var" in reason
    assert "STRIPE_API_KEY (payments.py:2)" in reason
    assert "Fix steps:" in reason
    assert "export STRIPE_API_KEY=" in reason
    assert reason.endswith(FINAL_INSTRUCTION)


def test_deny_never_spawned_the_command(tmp_repo, scrubbed_env):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    sentinel = tmp_repo.root / "deployed.txt"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"touch {sentinel} && ./deploy.sh"},
    }
    output = handle_hook(payload, tmp_repo.root, scrubbed_env)
    assert _decision(output) == "deny"
    assert not sentinel.exists()


def test_deploy_passing_gate_emits_no_decision(tmp_repo, scrubbed_env):
    """A passing gate must NOT auto-approve — the user's normal permission
    flow makes the final call. The pass is still recorded."""
    tmp_repo.write("svc.py", "x = 1\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest"])
    payload = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    output = handle_hook(payload, tmp_repo.root, scrubbed_env)
    assert output == NO_DECISION
    record = MemoryStore(tmp_repo.root / ".proofloop").get("chk_001")
    assert record is not None and record.gate_passed


def test_deny_cites_recall_on_recurrence(tmp_repo, scrubbed_env):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    payload = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    handle_hook(payload, tmp_repo.root, scrubbed_env)
    output = handle_hook(payload, tmp_repo.root, scrubbed_env)
    assert "recalled from chk_001" in _reason(output)


def test_custom_patterns_from_config(tmp_repo, scrubbed_env):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.write(".proofloop.toml", "[hook]\ndeploy_patterns = ['^make ship$']\n")
    ship = {"tool_name": "Bash", "tool_input": {"command": "make ship"}}
    other = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    assert _decision(handle_hook(ship, tmp_repo.root, scrubbed_env)) == "deny"
    assert handle_hook(other, tmp_repo.root, scrubbed_env) == NO_DECISION


def test_invalid_config_pattern_dropped_with_warning(tmp_repo, scrubbed_env, capsys):
    """One bad regex must not deny every Bash command (fail-closed lockout);
    it is dropped with a warning while valid patterns keep working."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.write(
        ".proofloop.toml", "[hook]\ndeploy_patterns = ['([', '^make ship$']\n"
    )
    ls = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    ship = {"tool_name": "Bash", "tool_input": {"command": "make ship"}}
    assert handle_hook(ls, tmp_repo.root, scrubbed_env) == NO_DECISION
    assert _decision(handle_hook(ship, tmp_repo.root, scrubbed_env)) == "deny"
    err = capsys.readouterr().err
    assert "invalid deploy pattern" in err
    assert "([" in err


def test_all_invalid_patterns_fall_back_to_defaults(tmp_repo, scrubbed_env, capsys):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    tmp_repo.write(".proofloop.toml", "[hook]\ndeploy_patterns = ['(']\n")
    deploy = {"tool_name": "Bash", "tool_input": {"command": "./deploy.sh"}}
    ls = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    assert _decision(handle_hook(deploy, tmp_repo.root, scrubbed_env)) == "deny"
    assert handle_hook(ls, tmp_repo.root, scrubbed_env) == NO_DECISION
    assert "invalid deploy pattern" in capsys.readouterr().err


def test_toml_template_patterns_mirror_defaults():
    """The .proofloop.toml template must parse, compile cleanly, and
    behave like DEFAULT_DEPLOY_PATTERNS (anchoring + word boundaries)."""
    import tomllib

    from proofloop.hooks import PROOFLOOP_TOML_TEMPLATE, get_deploy_patterns

    config = tomllib.loads(PROOFLOOP_TOML_TEMPLATE)
    patterns = get_deploy_patterns(config)
    assert patterns == DEFAULT_DEPLOY_PATTERNS
    compiled = compile_deploy_patterns(patterns)
    assert len(compiled) == len(patterns)  # every template pattern is valid
    assert is_deploy_command("./deploy.sh", compiled)
    assert is_deploy_command("bash deploy.sh", compiled)
    assert not is_deploy_command("cat deploy.sh", compiled)
    assert not is_deploy_command("git push origin prerelease", compiled)


def test_compile_deploy_patterns_drops_only_invalid():
    compiled = compile_deploy_patterns(["([", r"fly\s+deploy"])
    assert [p.pattern for p in compiled] == [r"fly\s+deploy"]
    fallback = compile_deploy_patterns(["(", "(("])
    assert [p.pattern for p in fallback] == DEFAULT_DEPLOY_PATTERNS


def test_is_proofloop_invocation():
    assert is_proofloop_invocation("proofloop guard deploy -- vercel --prod")
    assert is_proofloop_invocation("  FOO=bar BAZ='q x' proofloop run tests -- pytest")
    assert is_proofloop_invocation("/usr/local/bin/proofloop hook")
    assert not is_proofloop_invocation("vercel --prod")
    assert not is_proofloop_invocation("echo proofloop")
    assert not is_proofloop_invocation("")


def test_proofloop_invocations_never_re_gated(tmp_repo, scrubbed_env):
    """`proofloop guard deploy -- vercel --prod` matches the vercel pattern;
    re-gating it would double-run the gate and duplicate records."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    commands = [
        "proofloop guard deploy -- vercel --prod",
        "FOO=bar proofloop guard deploy -- vercel --prod",
        "/usr/local/bin/proofloop run tests -- pytest -q",
    ]
    for command in commands:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handle_hook(payload, tmp_repo.root, scrubbed_env) == NO_DECISION, command
    # the hook never ran the gate, so no records were written
    assert list(MemoryStore(tmp_repo.root / ".proofloop").iter_records()) == []


def test_hook_cli_reads_stdin_and_prints_no_decision(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    result = runner.invoke(app, ["hook"], input=payload)
    assert result.exit_code == 0
    output = json.loads(result.stdout.strip().splitlines()[-1])
    assert output == NO_DECISION


def test_hook_cli_denies_deploy_in_failing_repo(tmp_repo, monkeypatch):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["A_VAR_NOT_SET_ANYWHERE"]\n')
    monkeypatch.chdir(tmp_repo.root)
    monkeypatch.delenv("A_VAR_NOT_SET_ANYWHERE", raising=False)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "fly deploy"}})
    result = runner.invoke(app, ["hook"], input=payload)
    assert result.exit_code == 0
    output = json.loads(result.stdout.strip().splitlines()[-1])
    assert _decision(output) == "deny"
    assert _reason(output).endswith(FINAL_INSTRUCTION)

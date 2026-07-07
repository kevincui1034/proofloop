"""proofloop login / logout — BYOK key onboarding via the CLI."""

import stat

from typer.testing import CliRunner

from proofloop import config
from proofloop.cli import app
from proofloop.judge import AnthropicJudge, DeterministicJudge, OpenAIJudge, get_judge

runner = CliRunner()


def _point_config_at_tmp(monkeypatch, tmp_path):
    # Override the autouse offline fixture: real config path (tmp), LLM allowed.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("PROOFLOOP_NO_LLM", raising=False)


def test_login_writes_config_and_selects_adapter(monkeypatch, tmp_path):
    _point_config_at_tmp(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        ["login", "--provider", "anthropic", "--api-key", "sk-ant-xxxxxxxx", "--no-verify"],
    )
    assert result.exit_code == 0

    loaded = config.load_config()
    assert loaded["judge"]["provider"] == "anthropic"
    assert loaded["judge"]["api_key"] == "sk-ant-xxxxxxxx"
    assert stat.S_IMODE(config.config_path().stat().st_mode) == 0o600

    # masked key shown; full key never printed
    assert "sk-ant-xxxxxxxx" not in result.output
    assert "sk-…xxxx" in result.output

    judge = get_judge()
    assert isinstance(judge, AnthropicJudge)
    assert judge.api_key == "sk-ant-xxxxxxxx"


def test_logout_clears_config_and_falls_back(monkeypatch, tmp_path):
    _point_config_at_tmp(monkeypatch, tmp_path)
    runner.invoke(
        app,
        ["login", "--provider", "openai", "--api-key", "sk-openai-123", "--no-verify"],
    )
    assert isinstance(get_judge(), OpenAIJudge)

    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
    assert "openai" in result.output
    assert not config.config_path().exists()
    assert isinstance(get_judge(), DeterministicJudge)


def test_login_invalid_provider_exits_64(monkeypatch, tmp_path):
    _point_config_at_tmp(monkeypatch, tmp_path)
    result = runner.invoke(
        app, ["login", "--provider", "gemini", "--api-key", "k", "--no-verify"]
    )
    assert result.exit_code == 64  # EX_USAGE, never collides with BLOCKED (2)
    assert not config.config_path().exists()


def test_logout_when_nothing_stored(monkeypatch, tmp_path):
    _point_config_at_tmp(monkeypatch, tmp_path)
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
    assert "no stored judge config" in result.output

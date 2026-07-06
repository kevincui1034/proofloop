"""proofloop init: scaffolding + non-clobbering .claude/settings.json merge."""

import json

from typer.testing import CliRunner

from proofloop.cli import app

runner = CliRunner()


def _hook_commands(settings: dict) -> list[str]:
    return [
        hook["command"]
        for entry in settings.get("hooks", {}).get("PreToolUse", [])
        for hook in entry.get("hooks", [])
    ]


def test_init_scaffolds_everything(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / ".proofloop").is_dir()
    assert (tmp_repo.root / ".proofloop.toml").is_file()
    settings = json.loads((tmp_repo.root / ".claude" / "settings.json").read_text())
    assert "proofloop hook" in _hook_commands(settings)
    assert "proofloop guard deploy" in result.stdout  # AGENTS.md snippet printed


def test_init_merges_existing_settings_without_clobbering(tmp_repo, monkeypatch):
    existing = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": []}]},
    }
    tmp_repo.write(".claude/settings.json", json.dumps(existing))
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    merged = json.loads((tmp_repo.root / ".claude" / "settings.json").read_text())
    assert merged["permissions"] == {"allow": ["Bash(ls:*)"]}  # untouched
    assert merged["hooks"]["PostToolUse"] == existing["hooks"]["PostToolUse"]
    assert "proofloop hook" in _hook_commands(merged)


def test_init_is_idempotent(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    toml_before = (tmp_repo.root / ".proofloop.toml").read_text()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    settings = json.loads((tmp_repo.root / ".claude" / "settings.json").read_text())
    assert _hook_commands(settings).count("proofloop hook") == 1  # no duplicate
    assert (tmp_repo.root / ".proofloop.toml").read_text() == toml_before


def test_init_backs_off_on_invalid_settings_json(tmp_repo, monkeypatch):
    tmp_repo.write(".claude/settings.json", "{not json")
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / ".claude" / "settings.json").read_text() == "{not json"
    assert "not clobbering" in result.stdout

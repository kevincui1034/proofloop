"""proofjury init: scaffolding + non-clobbering .claude/settings.json merge."""

import json

from typer.testing import CliRunner

from proofjury.cli import app

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
    assert (tmp_repo.root / ".proofjury").is_dir()
    assert (tmp_repo.root / ".proofjury.toml").is_file()
    settings = json.loads((tmp_repo.root / ".claude" / "settings.json").read_text())
    assert "proofjury hook" in _hook_commands(settings)
    agents_md = (tmp_repo.root / "AGENTS.md").read_text()
    assert "proofjury guard deploy" in agents_md  # snippet auto-written
    assert agents_md.startswith("<!-- proofjury:start -->")
    assert "<!-- proofjury:end -->" in agents_md
    assert (tmp_repo.root / ".gitignore").read_text() == ".proofjury/\n"


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
    assert "proofjury hook" in _hook_commands(merged)


def test_init_is_idempotent(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    toml_before = (tmp_repo.root / ".proofjury.toml").read_text()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    settings = json.loads((tmp_repo.root / ".claude" / "settings.json").read_text())
    assert _hook_commands(settings).count("proofjury hook") == 1  # no duplicate
    assert (tmp_repo.root / ".proofjury.toml").read_text() == toml_before


def test_init_backs_off_on_invalid_settings_json(tmp_repo, monkeypatch):
    tmp_repo.write(".claude/settings.json", "{not json")
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / ".claude" / "settings.json").read_text() == "{not json"
    assert "not clobbering" in result.stdout


def test_render_toml_handles_single_quotes(tmp_repo, monkeypatch):
    """D5: a detected deploy script containing a single quote is emitted
    as an escaped TOML basic string, not silently dropped."""
    import re
    import tomllib

    from proofjury.cli import _render_proofjury_toml
    from proofjury.hooks import detect_extra_deploy_patterns

    tmp_repo.write(
        "package.json",
        json.dumps({"scripts": {"deploy:o'brien": "./ship.sh", "deploy:prod": "x"}}),
    )
    extras = detect_extra_deploy_patterns(tmp_repo.root)
    assert any("o" in p and "brien" in p for p in extras)

    rendered = _render_proofjury_toml(extras)
    parsed = tomllib.loads(rendered)  # round-trips as valid TOML
    patterns = parsed["hook"]["deploy_patterns_extra"]
    assert len(patterns) == len(extras)
    for original, parsed_pattern in zip(extras, patterns):
        assert parsed_pattern == original
        re.compile(parsed_pattern)  # still a valid regex after the round-trip


def test_init_merges_cursor_hooks_without_clobbering(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    existing = {
        "version": 1,
        "hooks": {
            "beforeShellExecution": [{"command": "my-other-hook"}],
            "afterFileEdit": [{"command": "format-on-save"}],
        },
    }
    tmp_repo.write(".cursor/hooks.json", json.dumps(existing))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    data = json.loads((tmp_repo.root / ".cursor" / "hooks.json").read_text())
    before = data["hooks"]["beforeShellExecution"]
    assert {"command": "my-other-hook"} in before  # unrelated entries survive
    assert {"command": "proofjury hook --agent cursor"} in before
    assert data["hooks"]["afterFileEdit"] == [{"command": "format-on-save"}]
    assert data["version"] == 1


def test_init_merges_codex_hooks_idempotent(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    (tmp_repo.root / ".codex").mkdir()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0
    path = tmp_repo.root / ".codex" / "hooks.json"
    written = path.read_text()
    data = json.loads(written)
    entry = data["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    assert entry["hooks"][0]["command"] == "proofjury hook --agent codex"
    assert "trust this folder" in first.stdout  # the Codex trust caveat

    second = runner.invoke(app, ["init"])
    assert second.exit_code == 0
    assert "already wired" in second.stdout
    assert path.read_text() == written  # byte-for-byte unchanged


def test_init_all_agents_flag_wires_everything(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init", "--all-agents"])
    assert result.exit_code == 0
    assert (tmp_repo.root / ".claude" / "settings.json").is_file()
    assert (tmp_repo.root / ".cursor" / "hooks.json").is_file()
    assert (tmp_repo.root / ".codex" / "hooks.json").is_file()


def test_init_backs_off_on_invalid_cursor_hooks_json(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    tmp_repo.write(".cursor/hooks.json", "{not json")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "not clobbering" in result.stdout
    assert (tmp_repo.root / ".cursor" / "hooks.json").read_text() == "{not json"


# -- AGENTS.md / CLAUDE.md snippet auto-write --------------------------------


def test_init_appends_snippet_to_existing_agents_md(tmp_repo, monkeypatch):
    tmp_repo.write("AGENTS.md", "# My rules\n\nUse tabs.\n")
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    text = (tmp_repo.root / "AGENTS.md").read_text()
    assert text.startswith("# My rules\n\nUse tabs.\n")  # prior content survives
    assert "<!-- proofjury:start -->" in text
    assert "proofjury guard deploy" in text


def test_init_agents_md_is_idempotent(tmp_repo, monkeypatch):
    tmp_repo.write("AGENTS.md", "# My rules\n")
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    first = (tmp_repo.root / "AGENTS.md").read_text()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / "AGENTS.md").read_text() == first  # byte-for-byte
    assert "already wired" in result.stdout


def test_init_replaces_stale_snippet_between_markers(tmp_repo, monkeypatch):
    tmp_repo.write(
        "AGENTS.md",
        "# Rules\n\n<!-- proofjury:start -->\nold snippet v0\n"
        "<!-- proofjury:end -->\n\n## After\n",
    )
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    text = (tmp_repo.root / "AGENTS.md").read_text()
    assert "old snippet v0" not in text
    assert "proofjury guard deploy" in text
    assert text.startswith("# Rules\n")
    assert text.endswith("\n## After\n")  # content after the block survives


def test_init_skips_claude_md_that_imports_agents_md(tmp_repo, monkeypatch):
    claude_md = "# Project\n\n@AGENTS.md\n"
    tmp_repo.write("CLAUDE.md", claude_md)
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / "CLAUDE.md").read_text() == claude_md  # untouched
    assert (tmp_repo.root / "AGENTS.md").is_file()  # snippet went here


def test_init_writes_existing_claude_md_without_import(tmp_repo, monkeypatch):
    tmp_repo.write("CLAUDE.md", "# Project conventions\n")
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    text = (tmp_repo.root / "CLAUDE.md").read_text()
    assert text.startswith("# Project conventions\n")
    assert "proofjury guard deploy" in text


def test_init_never_creates_claude_md(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert not (tmp_repo.root / "CLAUDE.md").exists()


def test_init_no_agents_md_prints_snippet_instead(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init", "--no-agents-md"])
    assert result.exit_code == 0
    assert not (tmp_repo.root / "AGENTS.md").exists()
    assert "proofjury guard deploy" in result.stdout  # printed fallback


def test_init_backs_off_on_mangled_markers(tmp_repo, monkeypatch):
    mangled = "# Rules\n\n<!-- proofjury:start -->\nno end marker\n"
    tmp_repo.write("AGENTS.md", mangled)
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / "AGENTS.md").read_text() == mangled  # untouched
    assert "not clobbering" in result.stdout
    assert "proofjury guard deploy" in result.stdout  # snippet printed as fallback


# -- .gitignore --------------------------------------------------------------


def test_init_appends_gitignore_without_clobbering(tmp_repo, monkeypatch):
    tmp_repo.write(".gitignore", "node_modules/\n*.log")  # no trailing newline
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    text = (tmp_repo.root / ".gitignore").read_text()
    assert text == "node_modules/\n*.log\n.proofjury/\n"


def test_init_gitignore_skips_when_already_covered(tmp_repo, monkeypatch):
    tmp_repo.write(".gitignore", "/.proofjury/\n")
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_repo.root / ".gitignore").read_text() == "/.proofjury/\n"
    assert "already covers" in result.stdout

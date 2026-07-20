"""proofjury status: read-only gate-readiness report (always exit 0)."""

import json

from typer.testing import CliRunner

from proofjury.cli import app

runner = CliRunner()


def test_status_on_fresh_repo_points_at_init(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert ".proofjury/ missing — run: proofjury init" in result.stdout
    assert ".proofjury.toml missing" in result.stdout
    assert "AGENTS.md gate instructions missing" in result.stdout
    assert "NOT STAMPED" in result.stdout  # tests called out explicitly


def test_status_after_init_shows_setup_and_hooks_green(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "✓ .proofjury/" in result.stdout
    assert "✓ .proofjury.toml" in result.stdout
    assert "✓ AGENTS.md gate instructions" in result.stdout
    assert ".claude/settings.json wired" in result.stdout
    assert "NOT STAMPED" in result.stdout  # nothing stamped yet


def test_status_fresh_stamp_shows_green(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "tests", "--", "true"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "✓ tests: fresh" in result.stdout
    assert "NOT STAMPED" not in result.stdout


def test_status_detects_digest_mismatch_after_edit(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "tests", "--", "true"])
    tmp_repo.write("app.py", "changed = True\n")  # edit after stamping
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "tests: code changed since the stamp" in result.stdout


def test_status_detects_stale_stamp(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "tests", "--", "true"])
    session_path = tmp_repo.root / ".proofjury" / "session.json"
    session = json.loads(session_path.read_text())
    session["tests"]["ran_at"] = "2020-01-01T00:00:00Z"
    session_path.write_text(json.dumps(session))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "tests: stale (older than 24h)" in result.stdout


def test_status_reports_failed_stamp(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    runner.invoke(app, ["run", "tests", "--", "false"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "tests: last run FAILED" in result.stdout


def test_status_path_warning_when_proofjury_unresolvable(tmp_repo, monkeypatch):
    import shutil

    monkeypatch.chdir(tmp_repo.root)
    real_which = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd, *a, **kw: None if cmd == "proofjury" else real_which(cmd, *a, **kw),
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "not on PATH" in result.stdout
    assert "uv tool install proofjury" in result.stdout


def test_status_path_warning_on_uvx_ephemeral_cache(tmp_repo, monkeypatch):
    import shutil

    monkeypatch.chdir(tmp_repo.root)
    fake = "/home/u/.cache/uv/archive-v0/abc123/bin/proofjury"
    real_which = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd, *a, **kw: fake if cmd == "proofjury" else real_which(cmd, *a, **kw),
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "ephemeral cache" in result.stdout


def test_status_counts_memory_records(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "0 record(s)" in result.stdout


def test_init_prints_next_steps(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Next:" in result.stdout
    assert "proofjury run tests --" in result.stdout
    assert "proofjury status" in result.stdout


def test_init_suggests_npm_test_for_node_repos(tmp_repo, monkeypatch):
    tmp_repo.write("package.json", json.dumps({"scripts": {"test": "vitest"}}))
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "proofjury run tests -- npm test" in result.stdout

"""tests_not_run / test_failure: marker lifecycle + `proofloop run` stamps."""

import json
import sys

from typer.testing import CliRunner

from proofloop.checks.tests import check_tests
from proofloop.cli import app
from proofloop.session import load_session, stamp

runner = CliRunner()


def test_marker_absent_fails_tests_not_run(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    result = check_tests(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "tests_not_run"
    assert "no test run recorded" in result.evidence[0].detail
    assert result.fix_hint == "Run: proofloop run tests -- pytest"


def test_fresh_passing_marker_passes(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest", "-q"])
    result = check_tests(make_ctx(tmp_repo.root))
    assert result.passed


def test_stale_digest_fails(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest"])
    tmp_repo.write("new_code.py", "y = 2\n")  # worktree changed after tests ran
    result = check_tests(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "tests_not_run"
    assert "code changed since tests last ran" in result.evidence[0].detail


def test_marker_older_than_24h_fails(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest"])
    session_file = tmp_repo.root / ".proofloop" / "session.json"
    data = json.loads(session_file.read_text())
    data["tests"]["ran_at"] = "2020-01-01T00:00:00Z"
    session_file.write_text(json.dumps(data))
    result = check_tests(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "tests_not_run"
    assert "older than 24h" in result.evidence[0].detail


def test_failed_marker_is_test_failure(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    stamp(tmp_repo.root, "tests", 1, ["pytest"])
    result = check_tests(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "test_failure"
    assert "exit code 1" in result.evidence[0].detail


def test_run_command_stamps_and_tees(tmp_repo, make_ctx, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(
        app, ["run", "tests", "--", sys.executable, "-c", "print('42-ran')"]
    )
    assert result.exit_code == 0
    assert "42-ran" in result.stdout
    session = load_session(tmp_repo.root)
    assert session["tests"]["exit_code"] == 0
    assert session["tests"]["cmd"][0] == sys.executable
    logs = list((tmp_repo.root / ".proofloop" / "runs").glob("tests-*.log"))
    assert len(logs) == 1
    assert "42-ran" in logs[0].read_text()
    # And the gate-facing check now passes.
    assert check_tests(make_ctx(tmp_repo.root)).passed


def test_run_command_propagates_exit_code(tmp_repo, make_ctx, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(
        app, ["run", "tests", "--", sys.executable, "-c", "import sys; sys.exit(4)"]
    )
    assert result.exit_code == 4
    check = check_tests(make_ctx(tmp_repo.root))
    assert check.failure_class == "test_failure"


def test_run_rejects_unknown_kind(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    result = runner.invoke(app, ["run", "bogus", "--", "echo", "hi"])
    assert result.exit_code == 64  # EX_USAGE — 2 is reserved for BLOCKED

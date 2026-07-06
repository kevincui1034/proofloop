"""build_failure / preprod_check_skipped, incl. skip-when-inapplicable."""

import json

from proofloop.checks.build import check_build
from proofloop.checks.preprod import check_preprod
from proofloop.session import stamp


def test_build_skipped_when_inapplicable(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    result = check_build(make_ctx(tmp_repo.root))
    assert result.passed
    assert result.skipped


def test_build_required_by_package_json_script(tmp_repo, make_ctx):
    tmp_repo.write("package.json", json.dumps({"scripts": {"build": "webpack"}}))
    result = check_build(make_ctx(tmp_repo.root))
    assert not result.passed
    assert not result.skipped
    assert result.failure_class == "build_failure"
    assert "no build recorded" in result.evidence[0].detail
    assert "proofloop run build -- npm run build" in result.fix_hint


def test_build_required_by_config_command(tmp_repo, make_ctx):
    config = {"commands": {"build": "make build"}}
    result = check_build(make_ctx(tmp_repo.root, config=config))
    assert not result.passed
    assert "proofloop run build -- make build" in result.fix_hint


def test_build_passes_with_fresh_marker(tmp_repo, make_ctx):
    config = {"commands": {"build": "make build"}}
    stamp(tmp_repo.root, "build", 0, ["make", "build"])
    result = check_build(make_ctx(tmp_repo.root, config=config))
    assert result.passed
    assert not result.skipped


def test_build_failed_marker(tmp_repo, make_ctx):
    config = {"commands": {"build": "make build"}}
    stamp(tmp_repo.root, "build", 1, ["make", "build"])
    result = check_build(make_ctx(tmp_repo.root, config=config))
    assert not result.passed
    assert "exit code 1" in result.evidence[0].detail


def test_build_stale_digest(tmp_repo, make_ctx):
    config = {"commands": {"build": "make build"}}
    stamp(tmp_repo.root, "build", 0, ["make", "build"])
    tmp_repo.write("changed.py", "y = 2\n")
    result = check_build(make_ctx(tmp_repo.root, config=config))
    assert not result.passed
    assert "code changed since the last build" in result.evidence[0].detail


def test_preprod_skipped_when_inapplicable(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    result = check_preprod(make_ctx(tmp_repo.root))
    assert result.passed
    assert result.skipped


def test_preprod_fails_when_lint_configured_but_not_run(tmp_repo, make_ctx):
    config = {"commands": {"lint": "ruff check ."}}
    result = check_preprod(make_ctx(tmp_repo.root, config=config))
    assert not result.passed
    assert result.failure_class == "preprod_check_skipped"
    assert "lint not run for this worktree" in result.evidence[0].detail
    assert "proofloop run lint -- ruff check ." in result.fix_hint


def test_preprod_passes_with_fresh_markers(tmp_repo, make_ctx):
    config = {"commands": {"lint": "ruff check .", "typecheck": "mypy ."}}
    stamp(tmp_repo.root, "lint", 0, ["ruff", "check", "."])
    stamp(tmp_repo.root, "typecheck", 0, ["mypy", "."])
    result = check_preprod(make_ctx(tmp_repo.root, config=config))
    assert result.passed
    assert not result.skipped


def test_preprod_reports_only_missing_kind(tmp_repo, make_ctx):
    config = {"commands": {"lint": "ruff check .", "typecheck": "mypy ."}}
    stamp(tmp_repo.root, "lint", 0, ["ruff", "check", "."])
    result = check_preprod(make_ctx(tmp_repo.root, config=config))
    assert not result.passed
    details = [e.detail for e in result.evidence]
    assert len(details) == 1
    assert "typecheck" in details[0]


def test_preprod_applicable_via_package_json(tmp_repo, make_ctx):
    tmp_repo.write("package.json", json.dumps({"scripts": {"lint": "eslint ."}}))
    result = check_preprod(make_ctx(tmp_repo.root))
    assert not result.passed
    assert "npm run lint" in result.fix_hint

"""worktree_digest: staged and untracked content must shift the digest."""

from proofjury.checks.tests import check_tests
from proofjury.session import stamp, worktree_digest


def test_staged_content_edit_changes_digest(tmp_repo):
    tmp_repo.write("svc.py", "x = 1\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-q", "-m", "base")
    # First edit, staged: this is the state the marker would be stamped in.
    tmp_repo.write("svc.py", "x = 2\n")
    tmp_repo.git("add", "svc.py")
    d1 = worktree_digest(tmp_repo.root)
    # Second edit, re-staged: `git status` text and the unstaged diff are
    # identical to before — only the staged CONTENT differs.
    tmp_repo.write("svc.py", "x = 3\n")
    tmp_repo.git("add", "svc.py")
    d2 = worktree_digest(tmp_repo.root)
    assert d1 != d2


def test_untracked_content_edit_changes_digest(tmp_repo):
    tmp_repo.write("new.py", "a = 1\n")
    d1 = worktree_digest(tmp_repo.root)
    # Same untracked path, new content: status output is unchanged.
    tmp_repo.write("new.py", "a = 2\n")
    d2 = worktree_digest(tmp_repo.root)
    assert d1 != d2


def test_staged_edit_after_stamp_invalidates_marker(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", "x = 1\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-q", "-m", "base")
    tmp_repo.write("svc.py", "x = 2\n")
    tmp_repo.git("add", "svc.py")
    stamp(tmp_repo.root, "tests", 0, ["pytest"])
    assert check_tests(make_ctx(tmp_repo.root)).passed
    tmp_repo.write("svc.py", "x = 3\n")
    tmp_repo.git("add", "svc.py")
    result = check_tests(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "tests_not_run"


def test_untracked_edit_after_stamp_invalidates_marker(tmp_repo, make_ctx):
    tmp_repo.write("new.py", "a = 1\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest"])
    assert check_tests(make_ctx(tmp_repo.root)).passed
    tmp_repo.write("new.py", "a = 2\n")
    result = check_tests(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "tests_not_run"


def test_proofjury_dir_never_affects_digest(tmp_repo):
    tmp_repo.write("svc.py", "x = 1\n")
    d1 = worktree_digest(tmp_repo.root)
    tmp_repo.write(".proofjury/session.json", "{}\n")
    tmp_repo.write(".proofjury/runs/tests-1.log", "log\n")
    d2 = worktree_digest(tmp_repo.root)
    assert d1 == d2


def test_non_git_fallback_still_content_hashes(tmp_path):
    (tmp_path / "svc.py").write_text("x = 1\n")
    d1 = worktree_digest(tmp_path)
    (tmp_path / "svc.py").write_text("x = 2\n")
    d2 = worktree_digest(tmp_path)
    assert d1 != d2

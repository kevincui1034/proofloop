"""Diff-scoped checks: pending_migration, lockfile_drift, unfinished_work.

All three skip outside a usable git context (no repo, no HEAD) — so they
never fire in the demo workdir or non-git trees.
"""

import pytest

from proofjury.checks.lockfile import check_lockfile
from proofjury.checks.migrations import check_migrations
from proofjury.checks.unfinished import check_unfinished
from proofjury.judge.deterministic import DeterministicJudge
from proofjury.judge.base import JudgeInput


@pytest.fixture
def committed_repo(tmp_repo):
    """A git repo with an initial commit so `git diff HEAD` has a basis."""
    tmp_repo.write("app.py", "x = 1\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    return tmp_repo


# -- skip-unless-applicable ----------------------------------------------


def test_all_three_skip_outside_git(tmp_path, make_ctx):
    (tmp_path / "app.py").write_text("x = 1\n")
    ctx = make_ctx(tmp_path)
    assert check_migrations(ctx).skipped
    assert check_lockfile(ctx).skipped
    # git status works without commits, but git diff HEAD needs a HEAD:
    assert check_unfinished(ctx).skipped


def test_unfinished_skips_in_repo_without_commits(tmp_repo, make_ctx):
    tmp_repo.write("app.py", "x = 1  # TODO\n")
    assert check_unfinished(make_ctx(tmp_repo.root)).skipped


# -- pending_migration ------------------------------------------------------


def test_prisma_schema_change_without_migration_fires(committed_repo, make_ctx):
    committed_repo.write("prisma/schema.prisma", "model User { id Int @id }\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "add schema")
    committed_repo.write("prisma/schema.prisma", "model User { id Int @id\n email String }\n")
    result = check_migrations(make_ctx(committed_repo.root))
    assert not result.passed
    assert result.failure_class == "pending_migration"
    assert result.evidence[0].file == "prisma/schema.prisma"


def test_prisma_schema_change_with_untracked_migration_passes(committed_repo, make_ctx):
    committed_repo.write("prisma/schema.prisma", "model User { id Int @id }\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "add schema")
    committed_repo.write("prisma/schema.prisma", "model User { id Int @id\n email String }\n")
    # the fresh migration is untracked — must still count as a migration change
    committed_repo.write("prisma/migrations/20260707_add_email/migration.sql", "ALTER TABLE ...\n")
    result = check_migrations(make_ctx(committed_repo.root))
    assert result.passed and not result.skipped


def test_django_models_change_without_migration_fires(committed_repo, make_ctx):
    committed_repo.write("manage.py", "#!/usr/bin/env python\n")
    committed_repo.write("shop/models.py", "class Item: pass\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "django app")
    committed_repo.write("shop/models.py", "class Item:\n    name = 'x'\n")
    result = check_migrations(make_ctx(committed_repo.root))
    assert result.failure_class == "pending_migration"
    committed_repo.write("shop/migrations/0002_item_name.py", "# migration\n")
    assert check_migrations(make_ctx(committed_repo.root)).passed


def test_custom_migration_rule_from_config(committed_repo, make_ctx):
    committed_repo.write("db/schema.rb", "create_table :users\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "schema")
    committed_repo.write("db/schema.rb", "create_table :users do |t| end\n")
    config = {"checks": {"migrations": {"schema": ["db/schema.rb"], "migrations_dir": "db/migrate"}}}
    result = check_migrations(make_ctx(committed_repo.root, config=config))
    assert result.failure_class == "pending_migration"
    committed_repo.write("db/migrate/002_change.rb", "# migration\n")
    assert check_migrations(make_ctx(committed_repo.root, config=config)).passed


def test_no_framework_markers_skips(committed_repo, make_ctx):
    committed_repo.write("app.py", "x = 2\n")
    assert check_migrations(make_ctx(committed_repo.root)).skipped


# -- lockfile_drift -----------------------------------------------------------


def test_manifest_change_without_lockfile_change_fires(committed_repo, make_ctx):
    committed_repo.write("package.json", '{"dependencies": {}}\n')
    committed_repo.write("package-lock.json", "{}\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "npm project")
    committed_repo.write("package.json", '{"dependencies": {"left-pad": "^1"}}\n')
    result = check_lockfile(make_ctx(committed_repo.root))
    assert result.failure_class == "lockfile_drift"
    assert result.evidence[0].file == "package.json"
    assert "package-lock.json" in result.evidence[0].detail


def test_manifest_and_lockfile_together_pass(committed_repo, make_ctx):
    committed_repo.write("package.json", '{"dependencies": {}}\n')
    committed_repo.write("yarn.lock", "\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "yarn project")
    committed_repo.write("package.json", '{"dependencies": {"a": "1"}}\n')
    committed_repo.write("yarn.lock", "a@1:\n")
    result = check_lockfile(make_ctx(committed_repo.root))
    assert result.passed and not result.skipped


def test_manifest_without_any_lockfile_skips(committed_repo, make_ctx):
    committed_repo.write("package.json", '{"name": "x"}\n')
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "no lockfile")
    committed_repo.write("package.json", '{"name": "y"}\n')
    assert check_lockfile(make_ctx(committed_repo.root)).skipped


def test_workspace_manifest_uses_sibling_lockfile(committed_repo, make_ctx):
    committed_repo.write("apps/web/package.json", "{}\n")
    committed_repo.write("apps/web/package-lock.json", "{}\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "workspace")
    committed_repo.write("apps/web/package.json", '{"dependencies": {"a": "1"}}\n')
    result = check_lockfile(make_ctx(committed_repo.root))
    assert result.failure_class == "lockfile_drift"
    assert result.evidence[0].file == "apps/web/package.json"


def test_pyproject_uv_lock_pair(committed_repo, make_ctx):
    committed_repo.write("pyproject.toml", "[project]\nname='x'\n")
    committed_repo.write("uv.lock", "\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "py project")
    committed_repo.write("pyproject.toml", "[project]\nname='x'\ndependencies=['httpx']\n")
    assert check_lockfile(make_ctx(committed_repo.root)).failure_class == "lockfile_drift"


# -- unfinished_work -----------------------------------------------------------


def test_added_todo_fires_with_line_anchor(committed_repo, make_ctx):
    committed_repo.write("app.py", "x = 1\ny = 2  # TODO: wire this up\n")
    result = check_unfinished(make_ctx(committed_repo.root))
    assert result.failure_class == "unfinished_work"
    assert result.evidence[0].file == "app.py"
    assert result.evidence[0].line == 2
    assert "TODO" in result.evidence[0].detail


def test_added_not_implemented_fires(committed_repo, make_ctx):
    committed_repo.write("app.py", "x = 1\ndef f():\n    raise NotImplementedError\n")
    result = check_unfinished(make_ctx(committed_repo.root))
    assert result.failure_class == "unfinished_work"
    assert result.evidence[0].line == 3


def test_committed_todo_does_not_fire(committed_repo, make_ctx):
    """Diff-scoped, not tree-scoped: a long-lived TODO is a backlog item."""
    committed_repo.write("app.py", "x = 1  # TODO: someday\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "todo committed")
    result = check_unfinished(make_ctx(committed_repo.root))
    assert result.passed and not result.skipped


def test_lowercase_todo_in_prose_does_not_fire(committed_repo, make_ctx):
    committed_repo.write("app.py", 'x = 1\nmsg = "update your todos"\n')
    assert check_unfinished(make_ctx(committed_repo.root)).passed


# -- judge integration -----------------------------------------------------


def test_new_classes_get_specific_sentences(committed_repo, make_ctx):
    committed_repo.write("prisma/schema.prisma", "model A { id Int @id }\n")
    committed_repo.git("add", ".")
    committed_repo.git("commit", "-qm", "schema")
    committed_repo.write("prisma/schema.prisma", "model A { id Int @id\n b Int }\n")
    failure = check_migrations(make_ctx(committed_repo.root))
    output = DeterministicJudge().diagnose(
        JudgeInput(action="deploy", repo_id="r", failures=[failure], git_summary="")
    )
    assert "schema change has no accompanying migration" in output.diagnosis
    assert output.fix_steps  # fix_hint compiled, not the generic fallback

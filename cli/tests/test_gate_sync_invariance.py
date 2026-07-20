"""PINNED: gate exit codes and output are bit-identical with sync enabled
(and broken) vs disabled. Deterministic checks alone own the decision;
sync is transport, not judgment."""

import pytest
from typer.testing import CliRunner

from proofjury.cli import app
from proofjury.config import save_sync_config
from proofjury.session import stamp

runner = CliRunner()


@pytest.fixture
def synced_env(tmp_path_factory, monkeypatch):
    """[sync] enabled pointing at an unreachable endpoint."""
    config_home = tmp_path_factory.mktemp("sync-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    env = {"XDG_CONFIG_HOME": str(config_home)}
    save_sync_config("pjt_test", "tok-1", env=env)
    monkeypatch.setenv("PROOFJURY_SYNC_URL", "http://127.0.0.1:9")  # closed port
    monkeypatch.delenv("PROOFJURY_NO_SYNC", raising=False)
    # Both arms share XDG_CONFIG_HOME (the [sync] table lives there), which
    # also hosts the cross-repo recall registry — disable recall so arm 2
    # can't cite arm 1 and shadow the sync on/off comparison.
    monkeypatch.setenv("PROOFJURY_NO_CROSS_REPO", "1")


def _guard(monkeypatch, no_sync: bool):
    if no_sync:
        monkeypatch.setenv("PROOFJURY_NO_SYNC", "1")
    else:
        monkeypatch.delenv("PROOFJURY_NO_SYNC", raising=False)
    return runner.invoke(app, ["guard", "deploy", "--no-exec"])


def test_blocked_exit_identical_with_unreachable_sync(
    tmp_path_factory, synced_env, monkeypatch
):
    """Two identical fresh repos — one synced arm, one killed arm — so
    memory recall (a second run in the SAME repo would recall the first)
    can't shadow the comparison."""
    import subprocess

    def fresh_repo(name):
        root = tmp_path_factory.mktemp(name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "payments.py").write_text(
            'import os\nKEY = os.environ["STRIPE_API_KEY"]\n'
        )
        return root

    arm_sync = fresh_repo("arm-sync")
    monkeypatch.chdir(arm_sync)
    with_sync = _guard(monkeypatch, no_sync=False)

    arm_off = fresh_repo("arm-off")
    monkeypatch.chdir(arm_off)
    without_sync = _guard(monkeypatch, no_sync=True)

    assert with_sync.exit_code == without_sync.exit_code == 2
    # Identical up to the repo-name-derived identity in the panel.
    normalize = lambda s: s.replace(arm_sync.name, "REPO").replace(
        arm_off.name, "REPO"
    )
    assert normalize(with_sync.output) == normalize(without_sync.output)


def test_passing_exit_identical_with_unreachable_sync(
    tmp_repo, synced_env, monkeypatch
):
    tmp_repo.write("svc.py", "def add(a, b):\n    return a + b\n")
    stamp(tmp_repo.root, "tests", 0, ["pytest", "-q"])
    monkeypatch.chdir(tmp_repo.root)
    with_sync = _guard(monkeypatch, no_sync=False)
    without_sync = _guard(monkeypatch, no_sync=True)
    assert with_sync.exit_code == without_sync.exit_code == 0


def test_exit_identical_when_sync_module_raises(tmp_repo, synced_env, monkeypatch):
    """Even a crashing sync layer never touches the decision."""
    import proofjury.sync as sync_module

    def explode(root, env):
        raise RuntimeError("sync layer crashed")

    monkeypatch.setattr(sync_module, "sync_after_gate", explode)
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    monkeypatch.chdir(tmp_repo.root)
    result = _guard(monkeypatch, no_sync=False)
    assert result.exit_code == 2

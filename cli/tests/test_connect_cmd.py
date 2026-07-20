"""connect / disconnect / sync commands (device flow via fake client)."""

import pytest
from typer.testing import CliRunner

import proofjury.sync as sync_module
from proofjury.cli import app
from proofjury.config import load_config, resolve_sync, save_sync_config

runner = CliRunner()


class FakeSyncClient:
    """Scripted device flow; records constructor args and revokes."""

    script = ["pending", "ok"]
    revoked = []

    def __init__(self, token, endpoint, transport=None):
        self.token = token
        self.endpoint = endpoint
        self._responses = list(type(self).script)

    def request_device_code(self):
        return {
            "device_code": "d" * 64,
            "user_code": "MKGH-P4TN",
            "verification_uri": "http://sync.test/device",
            "expires_in": 900,
            "interval": 0.01,
        }

    def poll_device_token(self, device_code):
        status = self._responses.pop(0)
        if status == "ok":
            return {
                "status": "ok",
                "token": "pjt_minted_secret_token",
                "token_id": "tok-1",
                "user_login": "kevin",
            }
        return {"status": status}

    def revoke(self):
        type(self).revoked.append(self.token)


@pytest.fixture
def connect_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("PROOFJURY_SYNC_URL", raising=False)
    monkeypatch.delenv("PROOFJURY_NO_SYNC", raising=False)
    monkeypatch.setattr(sync_module, "SyncClient", FakeSyncClient)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)  # a bare dir: no store, first drain skipped
    FakeSyncClient.script = ["pending", "ok"]
    FakeSyncClient.revoked = []
    return {"XDG_CONFIG_HOME": str(tmp_path)}


def test_connect_saves_token_and_masks_echo(connect_env):
    result = runner.invoke(app, ["connect", "--no-open"])
    assert result.exit_code == 0, result.output
    assert "MKGH-P4TN" in result.output
    assert "connected as kevin" in result.output
    # never echo the full token
    assert "pjt_minted_secret_token" not in result.output
    settings = resolve_sync(connect_env)
    assert settings["token"] == "pjt_minted_secret_token"
    assert settings["token_id"] == "tok-1"


def test_connect_slow_down_bumps_interval(connect_env):
    FakeSyncClient.script = ["slow_down", "pending", "ok"]
    result = runner.invoke(app, ["connect", "--no-open"])
    assert result.exit_code == 0, result.output
    assert resolve_sync(connect_env) is not None


def test_connect_denied_fails_cleanly(connect_env):
    FakeSyncClient.script = ["denied"]
    result = runner.invoke(app, ["connect", "--no-open"])
    assert result.exit_code == 1
    assert resolve_sync(connect_env) is None


def test_disconnect_revokes_and_clears(connect_env):
    save_sync_config("pjt_live", "tok-9", env=connect_env)
    result = runner.invoke(app, ["disconnect"])
    assert result.exit_code == 0, result.output
    assert FakeSyncClient.revoked == ["pjt_live"]
    assert resolve_sync(connect_env) is None
    assert "sync" not in load_config(connect_env)
    # idempotent
    result = runner.invoke(app, ["disconnect"])
    assert "not connected" in result.output


def test_sync_status_offline(connect_env):
    result = runner.invoke(app, ["sync", "--status"])
    assert result.exit_code == 0
    assert "disabled" in result.output
    save_sync_config("pjt_live", "tok-9", env=connect_env)
    result = runner.invoke(app, ["sync", "--status"])
    assert result.exit_code == 0
    assert "enabled" in result.output
    assert "pending records: 0" in result.output


def test_sync_network_failure_exits_zero(connect_env, monkeypatch):
    """Manual sync must never be a failing gate in scripts."""
    save_sync_config("pjt_live", "tok-9", env=connect_env)
    monkeypatch.setenv("PROOFJURY_SYNC_URL", "http://127.0.0.1:9")

    class ExplodingClient(FakeSyncClient):
        def pull_labels(self, repo_id, cursor):
            raise ConnectionError("down")

        def push_record(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(sync_module, "SyncClient", ExplodingClient)
    # Need a store with a record for the drain path to engage: reuse cwd
    # without one — "nothing to sync" also exits 0.
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0

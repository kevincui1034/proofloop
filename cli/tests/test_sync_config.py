"""[sync] config table: save/clear/resolve + kill-switch precedence."""

import os
import sys

import pytest

from proofjury.config import (
    DEFAULT_SYNC_ENDPOINT,
    clear_sync_config,
    config_path,
    load_config,
    resolve_sync,
    save_judge_config,
    save_sync_config,
    sync_enabled,
)


@pytest.fixture
def env(tmp_path):
    return {"XDG_CONFIG_HOME": str(tmp_path)}


def test_save_and_resolve_roundtrip(env):
    path = save_sync_config("pjt_secret123", "tok-id-1", env=env)
    assert path == config_path(env)
    settings = resolve_sync(env)
    assert settings == {
        "token": "pjt_secret123",
        "token_id": "tok-id-1",
        "endpoint": DEFAULT_SYNC_ENDPOINT.rstrip("/"),
    }
    assert sync_enabled(env)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_file_mode_is_0600(env):
    path = save_sync_config("pjt_x", "t", env=env)
    assert (path.stat().st_mode & 0o777) == 0o600


def test_save_preserves_judge_table(env):
    save_judge_config("openrouter", "sk-or-key", env=env)
    save_sync_config("pjt_x", "t", env=env)
    config = load_config(env)
    assert config["judge"]["api_key"] == "sk-or-key"
    assert config["sync"]["token"] == "pjt_x"
    # and clearing sync keeps judge
    assert clear_sync_config(env) == "t"
    config = load_config(env)
    assert "sync" not in config
    assert config["judge"]["provider"] == "openrouter"


def test_clear_deletes_file_when_only_sync(env):
    save_sync_config("pjt_x", "t", env=env)
    assert clear_sync_config(env) == "t"
    assert not config_path(env).exists()
    assert clear_sync_config(env) is None  # idempotent


def test_no_sync_env_var_beats_config(env):
    save_sync_config("pjt_x", "t", env=env)
    killed = dict(env, PROOFJURY_NO_SYNC="1")
    assert resolve_sync(killed) is None
    assert not sync_enabled(killed)


def test_enabled_false_disables(env, tmp_path):
    save_sync_config("pjt_x", "t", env=env)
    # flip enabled=false by hand (the writer always writes true)
    path = config_path(env)
    path.write_text(path.read_text().replace("enabled = true", "enabled = false"))
    assert resolve_sync(env) is None


def test_endpoint_precedence(env):
    save_sync_config("pjt_x", "t", endpoint="https://custom.example/api/v1", env=env)
    assert resolve_sync(env)["endpoint"] == "https://custom.example/api/v1"
    overridden = dict(env, PROOFJURY_SYNC_URL="http://localhost:3000/api/v1/")
    assert resolve_sync(overridden)["endpoint"] == "http://localhost:3000/api/v1"


def test_default_endpoint_not_persisted(env):
    save_sync_config("pjt_x", "t", endpoint=DEFAULT_SYNC_ENDPOINT, env=env)
    assert "endpoint" not in load_config(env)["sync"]


def test_missing_or_tokenless_config_disables(env):
    assert resolve_sync(env) is None
    save_sync_config("", "t", env=env)
    assert resolve_sync(env) is None

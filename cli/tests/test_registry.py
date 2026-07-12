"""User-level store registry — how cross-repo memory recall finds stores."""

import json
import sys

import pytest

from proofjury.memory import registry


def _env(tmp_path, **extra):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    env.update(extra)
    return env


def _store_root(tmp_path, name, with_jsonl=True):
    root = tmp_path / name / ".proofjury"
    root.mkdir(parents=True)
    if with_jsonl:
        (root / "memory.jsonl").write_text("")
    return root


# -- register / load ---------------------------------------------------------


def test_register_load_roundtrip(tmp_path):
    env = _env(tmp_path)
    root = _store_root(tmp_path, "repo-a")
    registry.register_store(root, "owner/repo-a", env)
    repos = registry.load_registry(env)["repos"]
    entry = repos[str(root.resolve())]
    assert entry["repo_id"] == "owner/repo-a"
    assert entry["last_seen"]


def test_register_same_store_twice_is_one_entry(tmp_path):
    env = _env(tmp_path)
    root = _store_root(tmp_path, "repo-a")
    registry.register_store(root, "repo-a", env)
    first_seen = registry.load_registry(env)["repos"][str(root.resolve())]["last_seen"]
    registry.register_store(root, "repo-a", env)
    repos = registry.load_registry(env)["repos"]
    assert len(repos) == 1
    assert repos[str(root.resolve())]["last_seen"] >= first_seen


def test_disabled_removes_entry(tmp_path):
    env = _env(tmp_path)
    root = _store_root(tmp_path, "repo-a")
    registry.register_store(root, "repo-a", env)
    registry.register_store(root, "repo-a", env, enabled=False)
    assert registry.load_registry(env)["repos"] == {}


def test_register_prunes_dead_paths(tmp_path):
    env = _env(tmp_path)
    dead = _store_root(tmp_path, "gone")
    registry.register_store(dead, "gone", env)
    import shutil

    shutil.rmtree(dead.parent)
    alive = _store_root(tmp_path, "alive")
    registry.register_store(alive, "alive", env)
    repos = registry.load_registry(env)["repos"]
    assert list(repos) == [str(alive.resolve())]


def test_load_missing_returns_empty_shell(tmp_path):
    assert registry.load_registry(_env(tmp_path)) == {
        "version": registry.REGISTRY_VERSION,
        "repos": {},
    }


def test_load_malformed_returns_empty_shell_and_register_rebuilds(tmp_path):
    env = _env(tmp_path)
    path = registry.registry_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json !!!")
    assert registry.load_registry(env)["repos"] == {}
    root = _store_root(tmp_path, "repo-a")
    registry.register_store(root, "repo-a", env)
    assert str(root.resolve()) in registry.load_registry(env)["repos"]


def test_registry_repos_not_a_dict_is_rebuilt(tmp_path):
    env = _env(tmp_path)
    path = registry.registry_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "repos": ["not", "a", "dict"]}))
    assert registry.load_registry(env)["repos"] == {}


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits drive the write failure"
)
def test_register_write_failure_is_swallowed(tmp_path):
    env = _env(tmp_path)
    cfg_dir = registry.registry_path(env).parent
    cfg_dir.mkdir(parents=True)
    cfg_dir.chmod(0o500)  # read-only parent: atomic write must fail
    try:
        registry.register_store(_store_root(tmp_path, "repo-a"), "repo-a", env)
    finally:
        cfg_dir.chmod(0o700)
    assert registry.load_registry(env)["repos"] == {}


# -- paths --------------------------------------------------------------------


def test_registry_path_xdg_and_home(tmp_path):
    assert (
        registry.registry_path({"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
        == tmp_path / "xdg" / "proofjury" / "registry.json"
    )
    assert (
        registry.registry_path({"HOME": str(tmp_path / "home")})
        == tmp_path / "home" / ".config" / "proofjury" / "registry.json"
    )


# -- foreign_stores ------------------------------------------------------------


def test_foreign_stores_excludes_local_root(tmp_path):
    env = _env(tmp_path)
    local = _store_root(tmp_path, "local")
    other = _store_root(tmp_path, "other")
    registry.register_store(local, "local", env)
    registry.register_store(other, "other", env)
    stores = registry.foreign_stores(local, env)
    assert [(rid, s.root) for rid, s in stores] == [("other", other.resolve())]


def test_foreign_stores_skips_missing_jsonl(tmp_path):
    env = _env(tmp_path)
    local = _store_root(tmp_path, "local")
    empty = _store_root(tmp_path, "no-records", with_jsonl=False)
    registry.register_store(empty, "no-records", env)
    assert registry.foreign_stores(local, env) == []


def test_foreign_stores_caps_fanout_most_recent_first(tmp_path):
    env = _env(tmp_path)
    local = _store_root(tmp_path, "local")
    roots = [_store_root(tmp_path, f"repo-{i:02d}") for i in range(12)]
    for i, root in enumerate(roots):
        registry.register_store(root, f"repo-{i:02d}", env)
        # force strictly increasing last_seen without sleeping
        repos = registry.load_registry(env)["repos"]
        repos[str(root.resolve())]["last_seen"] = f"2026-07-01T00:00:{i:02d}Z"
        registry._atomic_write(
            registry.registry_path(env),
            json.dumps({"version": 1, "repos": repos}) + "\n",
        )
    stores = registry.foreign_stores(local, env)
    assert len(stores) == registry.DEFAULT_FANOUT
    assert stores[0][0] == "repo-11"  # most recently seen first
    assert all(rid not in ("repo-00", "repo-01") for rid, _ in stores)

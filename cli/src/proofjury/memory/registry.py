"""User-level registry of proofjury stores — memory recall across repos.

A machine accumulates one ``.proofjury/`` store per gated repo. The
registry is how a gate in one repo finds the others: JSON (not TOML —
the minimal TOML writer in config.py only renders flat scalar tables)
at ``${XDG_CONFIG_HOME:-~/.config}/proofjury/registry.json``, refreshed
on every gate run.

Writes are atomic-replace, last-writer-wins, no lock: a registration
lost to a concurrent write self-heals on the losing repo's next gate
run. Reads over foreign stores are lock-free — they go through
``MemoryStore.iter_records()``, which already skips torn/malformed
lines. Everything here is best-effort: a broken registry must never
fail a gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ..config import _atomic_write, config_path
from ..session import now_iso
from .store import MemoryStore

REGISTRY_VERSION = 1

#: Most-recently-seen foreign stores consulted per gate run.
DEFAULT_FANOUT = 10


def registry_path(env: Mapping[str, str] | None = None) -> Path:
    return config_path(env).with_name("registry.json")


def load_registry(env: Mapping[str, str] | None = None) -> dict:
    """Parse the registry; a fresh empty shell when missing/malformed."""
    empty = {"version": REGISTRY_VERSION, "repos": {}}
    try:
        data = json.loads(registry_path(env).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("repos"), dict):
        return empty
    return {"version": REGISTRY_VERSION, "repos": data["repos"]}


def register_store(
    store_root: Path,
    repo_id: str,
    env: Mapping[str, str] | None = None,
    *,
    enabled: bool = True,
) -> None:
    """Upsert this store (or remove it when ``enabled=False``).

    ``enabled=False`` is the ``[memory] cross_repo = false`` path:
    deregistration is how an opted-out repo stops being read by other
    repos' gates. Dead paths are pruned opportunistically. Never raises.
    """
    try:
        registry = load_registry(env)
        repos: dict = registry["repos"]
        key = str(Path(store_root).resolve())
        if enabled:
            repos[key] = {"repo_id": repo_id, "last_seen": now_iso()}
        else:
            repos.pop(key, None)
        for path in [p for p in repos if p != key and not Path(p).exists()]:
            del repos[path]
        _atomic_write(
            registry_path(env), json.dumps(registry, indent=2, sort_keys=True) + "\n"
        )
    except (OSError, ValueError):
        pass  # best-effort: registry trouble never fails a gate


def foreign_stores(
    local_store_root: Path,
    env: Mapping[str, str] | None = None,
    limit: int = DEFAULT_FANOUT,
) -> list[tuple[str, MemoryStore]]:
    """Readable foreign stores, most recently seen first, capped.

    Skips the local store and any registered path whose ``memory.jsonl``
    is gone (repo deleted/moved — pruned on the next registration).
    """
    local_key = str(Path(local_store_root).resolve())
    entries = []
    for path_str, entry in load_registry(env)["repos"].items():
        if path_str == local_key or not isinstance(entry, dict):
            continue
        path = Path(path_str)
        if not (path / "memory.jsonl").is_file():
            continue
        entries.append(
            (str(entry.get("last_seen") or ""), str(entry.get("repo_id") or path.parent.name), path)
        )
    entries.sort(reverse=True)
    return [(repo_id, MemoryStore(path)) for _seen, repo_id, path in entries[:limit]]

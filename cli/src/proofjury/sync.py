"""Opt-in record sync to the hosted dashboard — best-effort, never a gate.

The cloud is ingest + storage + visualization only: records leave this
machine already env-scrubbed, and nothing uploads until ``proofjury
connect``. Sync follows the advisory judge's firewall discipline — any
failure degrades to "not synced yet" and the gate's decision, output and
exit code are byte-identical with sync on, off, or broken. Kill switches:
``[sync] enabled = false`` and ``PROOFJURY_NO_SYNC``.

State is a sidecar file ``.proofjury/sync.json`` (never a record field —
the §5 record key set is pinned and is the dataset). Each record's hash is
remembered at push time, so a record mutated later (labels, resolutions)
re-pushes automatically: local label changes need no separate up-sync
protocol.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Mapping

import httpx

from . import __version__
from .config import _atomic_write, resolve_sync
from .memory.store import MemoryStore

TIMEOUT_SECONDS = 5.0
CONNECT_TIMEOUT_SECONDS = 3.0
#: Auto-sync after a gate run pushes at most this many records; the manual
#: ``proofjury sync`` drains everything.
AUTO_DRAIN_LIMIT = 20
#: Proof files larger than this are truncated before upload (the record
#: itself is never truncated).
MAX_PROOF_FILE_BYTES = 1_000_000
TRUNCATION_MARKER = "\n…[truncated by proofjury sync]\n"

STATE_VERSION = 1


class SyncClient:
    """Thin httpx wrapper over the dashboard /api/v1 endpoints.

    Raises on any failure — callers own the firewall. ``transport`` is
    injectable for tests (httpx.MockTransport), same pattern as the judge
    adapters; ``PROOFJURY_SYNC_URL`` overrides the endpoint.
    """

    endpoint_env = "PROOFJURY_SYNC_URL"

    def __init__(
        self,
        token: str | None,
        endpoint: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token = token
        self.endpoint = endpoint.rstrip("/")
        self.transport = transport

    def _client(self) -> httpx.Client:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.Client(
            transport=self.transport,
            headers=headers,
            timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
        )

    def request_device_code(self) -> dict:
        with self._client() as client:
            response = client.post(
                f"{self.endpoint}/device/code",
                json={"hostname": platform.node(), "cli_version": __version__},
            )
            response.raise_for_status()
            return response.json()

    def poll_device_token(self, device_code: str) -> dict:
        """One poll. ``{"status": "pending"|"slow_down"|"ok"|<error>}``."""
        with self._client() as client:
            response = client.post(
                f"{self.endpoint}/device/token", json={"device_code": device_code}
            )
            if response.status_code == 202:
                return {"status": "pending"}
            if response.status_code == 429:
                return {"status": "slow_down"}
            if response.status_code == 400:
                return {"status": response.json().get("error", "invalid")}
            response.raise_for_status()
            return {"status": "ok", **response.json()}

    def push_record(
        self,
        repo_id: str,
        record: dict,
        proof_files: dict[str, str],
        truncated: list[str],
    ) -> dict:
        with self._client() as client:
            response = client.post(
                f"{self.endpoint}/ingest",
                json={
                    "repo_id": repo_id,
                    "record": record,
                    "proof_files": proof_files,
                    "truncated_files": truncated,
                },
            )
            response.raise_for_status()
            return response.json()

    def pull_labels(self, repo_id: str, cursor: int) -> dict:
        with self._client() as client:
            response = client.get(
                f"{self.endpoint}/repos/{repo_id}/labels",
                params={"cursor": cursor},
            )
            response.raise_for_status()
            return response.json()

    def revoke(self) -> None:
        with self._client() as client:
            client.post(f"{self.endpoint}/disconnect", json={})


# ---------------------------------------------------------------- state


def state_path(proof_root: Path) -> Path:
    return Path(proof_root) / "sync.json"


def load_state(proof_root: Path) -> dict:
    """Sidecar state; corrupt or missing → empty (re-push is idempotent)."""
    try:
        data = json.loads(state_path(proof_root).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("records"), dict):
            data.setdefault("label_cursor", 0)
            return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {"version": STATE_VERSION, "records": {}, "label_cursor": 0}

def save_state(proof_root: Path, state: dict) -> None:
    _atomic_write(state_path(proof_root), json.dumps(state, ensure_ascii=False))


def record_hash(record_dict: dict) -> str:
    return hashlib.sha256(
        json.dumps(record_dict, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------- drain


def _proof_files(proof_root: Path, record) -> tuple[dict[str, str], list[str]]:
    """Read the run's proof files, truncating oversized ones."""
    files: dict[str, str] = {}
    truncated: list[str] = []
    run_dir = Path(proof_root) / "runs" / record.id
    for name in record.proof_refs:
        try:
            content = (run_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content.encode("utf-8")) > MAX_PROOF_FILE_BYTES:
            content = content[:MAX_PROOF_FILE_BYTES] + TRUNCATION_MARKER
            truncated.append(name)
        files[name] = content
    return files, truncated


def drain(
    store: MemoryStore,
    client: SyncClient,
    repo_id: str,
    limit: int | None = AUTO_DRAIN_LIMIT,
) -> int:
    """Push new/changed records; returns how many were pushed.

    Proof files ride along only on a record's FIRST push (they are
    immutable after the run); a later hash change re-sends the record
    JSON alone. State is saved after every success, so a mid-drain
    failure loses nothing.
    """
    state = load_state(store.root)
    pushed = 0
    for record in store.iter_records():
        if limit is not None and pushed >= limit:
            break
        current = record_hash(record.to_dict())
        known = state["records"].get(record.id)
        if known == current:
            continue
        if known is None:
            proof_files, truncated = _proof_files(store.root, record)
        else:
            proof_files, truncated = {}, []
        client.push_record(repo_id, record.to_dict(), proof_files, truncated)
        state["records"][record.id] = current
        save_state(store.root, state)
        pushed += 1
    return pushed


def pending_count(store: MemoryStore) -> int:
    """How many records the next drain would push (no network)."""
    state = load_state(store.root)
    return sum(
        1
        for record in store.iter_records()
        if state["records"].get(record.id) != record_hash(record.to_dict())
    )


def pull_labels_and_apply(
    store: MemoryStore, client: SyncClient, repo_id: str
) -> int:
    """Apply web-made label events to the local store; returns the count.

    The cursor advances only past successfully applied events, so a
    mid-batch failure resumes where it stopped. Applied changes re-push
    on the next drain (hash-diff), converging cloud and local.
    """
    state = load_state(store.root)
    applied = 0
    result = client.pull_labels(repo_id, int(state.get("label_cursor", 0)))
    for event in result.get("events", []):
        if event.get("kind") != "advisory_label":
            continue  # unknown kinds skip but still advance the cursor
        payload = event.get("payload") or {}
        store.label_advisory(
            event["record_id"],
            int(event.get("index") or 0),
            label=payload.get("label"),
            delivery=payload.get("delivery"),
            retraction=payload.get("retraction"),
        )
        applied += 1
        state["label_cursor"] = event["seq"]
        save_state(store.root, state)
    # No events applied but the server cursor moved (all skipped kinds).
    if result.get("events") and state.get("label_cursor", 0) < result.get(
        "cursor", 0
    ):
        state["label_cursor"] = result["cursor"]
        save_state(store.root, state)
    return applied


def repo_id_of(store: MemoryStore) -> str | None:
    """The repo identity the gate persisted (no duplicated derivation)."""
    try:
        cached = (Path(store.root) / "repo_id").read_text().strip()
        if cached:
            return cached
    except OSError:
        pass
    last = None
    for record in store.iter_records():
        last = record
    return last.repo_id if last is not None else None


# ---------------------------------------------------------------- hook


def sync_after_gate(root: Path, env: Mapping[str, str]) -> None:
    """Best-effort post-run sync — the guard hook body.

    Never raises past this boundary and does bounded work. Pull happens
    here (post-run), so a web-approved advisory is delivered by the NEXT
    gate event — deliberate: sync may never add pre-gate latency.
    """
    try:
        settings = resolve_sync(env)
        if settings is None:
            return
        proof_root = Path(root) / ".proofjury"
        store = MemoryStore(proof_root)
        repo_id = repo_id_of(store)
        if repo_id is None:
            return
        client = SyncClient(settings["token"], settings["endpoint"])
        try:
            pull_labels_and_apply(store, client, repo_id)
        except Exception:
            pass  # pull failure must not stop the push
        drain(store, client, repo_id, limit=AUTO_DRAIN_LIMIT)
    except Exception:
        pass

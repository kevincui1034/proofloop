"""sync.py: push payloads, hash-diff drain, label pull — all offline via
httpx.MockTransport (the judge-adapter test pattern)."""

import json

import httpx
import pytest

from proofjury.gate import run_gate
from proofjury.memory.store import MemoryStore
from proofjury.sync import (
    AUTO_DRAIN_LIMIT,
    SyncClient,
    drain,
    load_state,
    pending_count,
    pull_labels_and_apply,
    record_hash,
    repo_id_of,
    state_path,
    sync_after_gate,
)

ENDPOINT = "http://sync.test/api/v1"


class RecordingServer:
    """MockTransport handler that records ingest calls and serves labels."""

    def __init__(self, label_events=None, fail_ingest=False):
        self.ingested = []
        self.label_events = label_events or []
        self.fail_ingest = fail_ingest

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/ingest"):
            if self.fail_ingest:
                return httpx.Response(500, json={"error": "boom"})
            payload = json.loads(request.content)
            self.ingested.append((dict(request.headers), payload))
            return httpx.Response(
                200, json={"status": "ok", "record_id": payload["record"]["id"]}
            )
        if "/labels" in path:
            cursor = int(request.url.params.get("cursor", 0))
            events = [e for e in self.label_events if e["seq"] > cursor]
            new_cursor = events[-1]["seq"] if events else cursor
            return httpx.Response(200, json={"events": events, "cursor": new_cursor})
        if path.endswith("/disconnect"):
            return httpx.Response(200, json={"status": "revoked"})
        return httpx.Response(404)


@pytest.fixture
def gated_repo(tmp_repo, scrubbed_env):
    """A repo with one blocked gate record (env var failure)."""
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    run_gate(tmp_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    return tmp_repo


def _client(server, token="pjt_test"):
    return SyncClient(token, ENDPOINT, transport=server.transport())


def _store(repo):
    return MemoryStore(repo.root / ".proofjury")


def test_push_sends_bearer_and_payload_shape(gated_repo):
    server = RecordingServer()
    store = _store(gated_repo)
    pushed = drain(store, _client(server), "demo-repo")
    assert pushed == 1
    headers, payload = server.ingested[0]
    assert headers["authorization"] == "Bearer pjt_test"
    assert payload["repo_id"] == "demo-repo"
    assert payload["record"]["id"] == "chk_001"
    assert payload["record"]["gate_passed"] is False
    # First push carries the proof files
    assert set(payload["proof_files"]) == set(payload["record"]["proof_refs"])
    assert payload["truncated_files"] == []


def test_drain_skips_unchanged_and_repushes_changed(gated_repo):
    server = RecordingServer()
    store = _store(gated_repo)
    assert pending_count(store) == 1
    drain(store, _client(server), "demo-repo")
    assert pending_count(store) == 0
    assert drain(store, _client(server), "demo-repo") == 0  # unchanged → skip
    assert len(server.ingested) == 1

    # Relabel the record locally → hash changes → re-push WITHOUT files.
    store.update_resolution("chk_001", {"status": "accepted", "at": "2026-07-18"})
    assert pending_count(store) == 1
    assert drain(store, _client(server), "demo-repo") == 1
    _, payload = server.ingested[-1]
    assert payload["record"]["resolution"]["status"] == "accepted"
    assert payload["proof_files"] == {}


def test_drain_respects_limit(tmp_repo, scrubbed_env):
    tmp_repo.write("payments.py", 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n')
    for _ in range(3):
        run_gate(tmp_repo.root, "deploy", ["true"], env=scrubbed_env, render=False)
    server = RecordingServer()
    store = _store(tmp_repo)
    assert drain(store, _client(server), "r", limit=2) == 2
    assert pending_count(store) == 1
    assert AUTO_DRAIN_LIMIT >= 2


def test_corrupt_state_file_repushes_without_crash(gated_repo):
    server = RecordingServer()
    store = _store(gated_repo)
    drain(store, _client(server), "demo-repo")
    state_path(store.root).write_text("{not json")
    assert pending_count(store) == 1  # treated as empty
    assert drain(store, _client(server), "demo-repo") == 1  # idempotent re-push


def test_failed_push_keeps_record_pending(gated_repo):
    server = RecordingServer(fail_ingest=True)
    store = _store(gated_repo)
    with pytest.raises(httpx.HTTPStatusError):
        drain(store, _client(server), "demo-repo")
    assert pending_count(store) == 1


def test_pull_applies_labels_and_persists_cursor(tmp_repo, scrubbed_env, monkeypatch):
    # A record with a held advisory, via the mock advisory judge machinery.
    from tests.test_advisory import MockAdvisoryJudge, _finding

    tmp_repo.write("a.py", "x = 1\n")
    tmp_repo.git("add", ".")
    tmp_repo.git("commit", "-qm", "init")
    tmp_repo.write("a.py", "x = 2\n")
    judge = MockAdvisoryJudge(findings=[_finding(confidence=0.5)])  # held
    run_gate(
        tmp_repo.root, "deploy", None, no_exec=True, env=scrubbed_env,
        render=False, advisory_judge=judge,
    )
    store = _store(tmp_repo)
    record = next(iter(store.iter_records()))
    assert record.advisories[0]["delivery"] == "held"

    server = RecordingServer(
        label_events=[
            {
                "seq": 7,
                "record_id": record.id,
                "kind": "advisory_label",
                "index": 0,
                "payload": {"delivery": "staged"},
                "created_at": "2026-07-18T12:00:00Z",
            }
        ]
    )
    applied = pull_labels_and_apply(store, _client(server), "demo-repo")
    assert applied == 1
    updated = store.get(record.id)
    assert updated.advisories[0]["delivery"] == "staged"
    assert load_state(store.root)["label_cursor"] == 7
    # Second pull: nothing new past the cursor.
    assert pull_labels_and_apply(store, _client(server), "demo-repo") == 0


def test_pull_skips_unknown_records_but_advances(gated_repo):
    store = _store(gated_repo)
    server = RecordingServer(
        label_events=[
            {
                "seq": 3,
                "record_id": "chk_999",  # not in this store
                "kind": "advisory_label",
                "index": 0,
                "payload": {"label": "rejected"},
                "created_at": "2026-07-18T12:00:00Z",
            }
        ]
    )
    applied = pull_labels_and_apply(store, _client(server), "demo-repo")
    assert applied == 1  # label_advisory returns False but the event is consumed
    assert load_state(store.root)["label_cursor"] == 3


def test_repo_id_of_prefers_persisted_identity(gated_repo):
    store = _store(gated_repo)
    persisted = (gated_repo.root / ".proofjury" / "repo_id").read_text().strip()
    assert repo_id_of(store) == persisted


def test_sync_after_gate_is_firewalled(gated_repo, monkeypatch, tmp_path):
    """Unreachable endpoint + enabled config → no exception escapes."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from proofjury.config import save_sync_config

    env = {
        "XDG_CONFIG_HOME": str(tmp_path),
        "PROOFJURY_SYNC_URL": "http://127.0.0.1:9",  # nothing listens here
    }
    save_sync_config("pjt_x", "t", env=env)
    sync_after_gate(gated_repo.root, env)  # must not raise


def test_sync_after_gate_disabled_is_noop(gated_repo):
    sync_after_gate(gated_repo.root, {})  # no config at all → no-op, no raise

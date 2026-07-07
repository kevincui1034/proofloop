"""MemoryStore — append-only JSONL + human markdown under .proofloop/.

Local files, no DB. append() fsyncs (records are the asset); resolution
updates rewrite the JSONL atomically (tempfile + os.replace). All
writers — id allocation, append, resolution rewrite — serialize on an
exclusive lock over ``.proofloop/lock`` (flock on POSIX, msvcrt
byte-range lock on Windows) so concurrent gates never mint duplicate
ids or clobber each other's records.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

from .schema import MemoryRecord

_ID_RE = re.compile(r"chk_(\d+)$")


def _lock_file(fh) -> None:
    """Exclusive-lock an open file, blocking until acquired."""
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        return
    # msvcrt.locking locks a byte range starting at the CURRENT file
    # position (the lock file is opened append-ish, sitting at EOF), so
    # seek(0) first. LK_LOCK is not infinite-blocking like flock — it
    # retries ~10x1s then raises OSError — so retry until acquired:
    # writers must always serialize, never fail.
    fh.seek(0)
    while True:
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            break
        except OSError:
            time.sleep(0.1)


def _unlock_file(fh) -> None:
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return
    fh.seek(0)  # unlock the same 1-byte range the lock claimed
    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


class MemoryStore:
    def __init__(self, root: Path):
        self.root = Path(root)  # the .proofloop directory
        self.jsonl_path = self.root / "memory.jsonl"
        self.md_path = self.root / "memory.md"
        self.counter_path = self.root / "counter"
        self.lock_path = self.root / "lock"

    # -- locking -------------------------------------------------------------

    @contextmanager
    def _exclusive_lock(self):
        """Serialize writers across processes (lock on .proofloop/lock).

        POSIX: flock. Windows: msvcrt byte-range lock (see _lock_file).
        """
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as fh:
            _lock_file(fh)
            try:
                yield
            finally:
                _unlock_file(fh)

    # -- ids ---------------------------------------------------------------

    def _max_existing_id(self) -> int:
        """Highest id already claimed (runs/ dirs or JSONL records)."""
        max_n = 0
        runs_dir = self.root / "runs"
        if runs_dir.is_dir():
            for name in os.listdir(runs_dir):
                match = _ID_RE.match(name)
                if match:
                    max_n = max(max_n, int(match.group(1)))
        for record in self.iter_records():
            match = _ID_RE.match(record.id)
            if match:
                max_n = max(max_n, int(match.group(1)))
        return max_n

    def next_id(self) -> str:
        """Mint the next record id, atomically claiming runs/chk_N.

        Under the exclusive lock: never regress below the max existing
        id, and claim the id by creating its runs/ directory with
        exist_ok=False (bumping on collision) so two gates can never
        share a proof directory even if the counter file is tampered.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        with self._exclusive_lock():
            current = 0
            if self.counter_path.is_file():
                try:
                    current = int(self.counter_path.read_text().strip() or 0)
                except ValueError:
                    current = 0
            current = max(current, self._max_existing_id())
            runs_dir = self.root / "runs"
            while True:
                current += 1
                record_id = f"chk_{current:03d}"
                try:
                    os.makedirs(runs_dir / record_id, exist_ok=False)
                except FileExistsError:
                    continue  # already claimed — bump and retry
                break
            self.counter_path.write_text(str(current))
            return record_id

    # -- append ------------------------------------------------------------

    def append(self, record: MemoryRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with self._exclusive_lock():
            # A crash-truncated final line must not glue onto this record:
            # if the file doesn't end with \n, start on a fresh line.
            needs_newline = False
            if self.jsonl_path.is_file() and self.jsonl_path.stat().st_size > 0:
                with self.jsonl_path.open("rb") as fh:
                    fh.seek(-1, os.SEEK_END)
                    needs_newline = fh.read(1) != b"\n"
            with self.jsonl_path.open("a", encoding="utf-8") as fh:
                if needs_newline:
                    fh.write("\n")
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    def append_markdown(self, record: MemoryRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        is_new = not self.md_path.exists()
        verdict = "✅ PASSED" if record.gate_passed else "⛔ BLOCKED"
        failed = record.failed_checks()
        lines = [
            f"## {record.id} · {record.action_intercepted} · {verdict} · {record.created_at}",
            f"- **repo**: {record.repo_id} · agent: {record.agent_source}",
        ]
        if failed:
            summary = "; ".join(
                f"{c['name']} → {c.get('failure_class')}" for c in failed
            )
            lines.append(f"- **failed**: {summary}")
            for c in failed:
                if c.get("evidence"):
                    lines.append(f"- **evidence** ({c['name']}): {c['evidence']}")
        lines.append(f"- **diagnosis**: {record.diagnosis}")
        if record.recalled_from:
            lines.append(f"- **recalled_from**: {record.recalled_from}")
        if record.resolves:
            lines.append(f"- **resolves**: {record.resolves}")
        lines.append(f"- **proof**: {record.context_ref}")
        lines.append("")
        with self.md_path.open("a", encoding="utf-8") as fh:
            if is_new:
                fh.write("# Proofloop memory\n\n")
            fh.write("\n".join(lines) + "\n")

    # -- read --------------------------------------------------------------

    def iter_records(self) -> Iterator[MemoryRecord]:
        if not self.jsonl_path.is_file():
            return
        with self.jsonl_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield MemoryRecord.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError):
                    continue

    def get(self, record_id: str) -> MemoryRecord | None:
        for record in self.iter_records():
            if record.id == record_id:
                return record
        return None

    # -- update ------------------------------------------------------------

    def label_advisory(
        self,
        record_id: str,
        index: int,
        label: str | None = None,
        delivery: str | None = None,
        retraction: str | None = None,
    ) -> bool:
        """Update one advisory entry's lifecycle fields via atomic rewrite.

        Only the fields given (non-None) are set — label, delivery and
        retraction advance independently (e.g. a drain marks delivery
        "sent" without touching the label). Same lock/tempfile path as
        ``update_resolution``, so concurrent appends are never dropped.
        """
        if not self.jsonl_path.is_file():
            return False
        with self._exclusive_lock():
            found = False
            out_lines: list[str] = []
            with self.jsonl_path.open(encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        data = json.loads(stripped)
                    except json.JSONDecodeError:
                        out_lines.append(stripped)
                        continue
                    if data.get("id") == record_id:
                        advisories = data.get("advisories") or []
                        if 0 <= index < len(advisories) and isinstance(
                            advisories[index], dict
                        ):
                            entry = advisories[index]
                            if label is not None:
                                entry["label"] = label
                            if delivery is not None:
                                entry["delivery"] = delivery
                            if retraction is not None:
                                entry["retraction"] = retraction
                            found = True
                    out_lines.append(json.dumps(data, ensure_ascii=False))
            if not found:
                return False
            fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".memory-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(out_lines) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.jsonl_path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return True

    def update_resolution(self, record_id: str, resolution: dict) -> bool:
        """Set ``resolution`` on one record via atomic rewrite.

        A prior resolution is never clobbered: it is pushed onto
        ``resolution["history"]`` — a flat, chronological (oldest-first)
        list of prior resolution dicts, each stripped of its own
        ``history`` key. Top-level ``status`` is always the current
        status; there is no ``history`` key at all when there was no
        prior resolution.

        The read → rewrite → replace happens under the same lock append()
        takes, so a concurrently appended record can never be dropped by
        the snapshot rewrite.
        """
        if not self.jsonl_path.is_file():
            return False
        with self._exclusive_lock():
            found = False
            out_lines: list[str] = []
            with self.jsonl_path.open(encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        data = json.loads(stripped)
                    except json.JSONDecodeError:
                        out_lines.append(stripped)
                        continue
                    if data.get("id") == record_id:
                        prev = data.get("resolution")
                        new_res = dict(resolution)
                        if isinstance(prev, dict):
                            prev_history = prev.pop("history", [])
                            new_res["history"] = [*prev_history, prev]
                        data["resolution"] = new_res
                        found = True
                    out_lines.append(json.dumps(data, ensure_ascii=False))
            if not found:
                return False
            fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".memory-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(out_lines) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.jsonl_path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return True

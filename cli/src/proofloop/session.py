"""Session markers: how the gate knows tests/build/lint/typecheck ran.

``proofloop run <kind> -- <cmd>`` stamps ``.proofloop/session.json`` with
``{kind: {ran_at, exit_code, cmd, worktree_digest}}``. The digest binds
the marker to the exact worktree contents, so editing code after running
tests invalidates the marker (tests_not_run).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .context import iter_source_files

MAX_MARKER_AGE_HOURS = 24

#: Untracked files larger than this are represented in the digest by
#: their status entry only (path + presence), not their content bytes.
MAX_UNTRACKED_HASH_BYTES = 1_000_000


def session_path(root: Path) -> Path:
    return Path(root) / ".proofloop" / "session.json"


def load_session(root: Path) -> dict:
    path = session_path(root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _drop_proofloop_status_lines(status: str) -> str:
    """Proofloop's own state dir must never count as 'code changed'."""
    return "\n".join(
        line for line in status.splitlines() if ".proofloop" not in line
    )


def _drop_proofloop_diff_sections(diff: str) -> str:
    parts = diff.split("diff --git ")
    kept = [parts[0]] + [
        part for part in parts[1:] if ".proofloop" not in part.split("\n", 1)[0]
    ]
    return "diff --git ".join(kept)


def _untracked_paths_from_status(status: str) -> list[str]:
    """Relative paths of ``??`` entries in porcelain status output."""
    paths: list[str] = []
    for line in status.splitlines():
        if not line.startswith("??"):
            continue
        path = line[3:]
        # Git C-quotes paths with special characters; unquote cheaply.
        if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
            try:
                path = path[1:-1].encode("latin-1").decode("unicode_escape")
            except (UnicodeDecodeError, UnicodeEncodeError):
                path = path[1:-1]
        paths.append(path)
    return paths


def worktree_digest(root: Path) -> str:
    """Digest of the current worktree state.

    Git repo: sha1 over ``git status --porcelain -uall`` output + a hash
    of ``git diff HEAD`` (staged AND unstaged changes to tracked files)
    + HEAD sha (so committed changes still shift the digest) + the
    content bytes of every untracked (``??``) file, so editing a
    still-untracked file after stamping invalidates the marker too.
    Otherwise: a content hash of all tracked (source-walked) files.
    ``.proofloop/`` itself is excluded — gate bookkeeping is not code.
    """
    root = Path(root)
    try:
        # -uall lists untracked files individually (not collapsed to a
        # directory entry) so each one can be content-hashed below.
        status = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=root, capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        status = _drop_proofloop_status_lines(status)
        head_cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
        head = head_cp.stdout.strip() if head_cp.returncode == 0 else ""
        # `git diff HEAD` covers staged + unstaged edits to tracked files
        # (plain `git diff` is blind to staged content). On an unborn
        # branch (no commits yet) HEAD does not resolve, so fall back to
        # worktree-vs-index + index-vs-empty diffs.
        if head:
            diff = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=root, capture_output=True, text=True, timeout=10, check=True,
            ).stdout
        else:
            diff = subprocess.run(
                ["git", "diff"],
                cwd=root, capture_output=True, text=True, timeout=10, check=True,
            ).stdout
            cached_cp = subprocess.run(
                ["git", "diff", "--cached"],
                cwd=root, capture_output=True, text=True, timeout=10,
            )
            if cached_cp.returncode == 0:
                diff += cached_cp.stdout
        diff = _drop_proofloop_diff_sections(diff)
        h = hashlib.sha1()
        h.update(status.encode())
        h.update(hashlib.sha1(diff.encode()).hexdigest().encode())
        h.update(head.encode())
        # Untracked files never appear in any diff — hash their content
        # so post-stamp edits to them still shift the digest.
        for relpath in sorted(_untracked_paths_from_status(status)):
            if ".proofloop" in Path(relpath).parts:
                continue
            f = root / relpath
            try:
                if not f.is_file() or f.stat().st_size > MAX_UNTRACKED_HASH_BYTES:
                    continue
                h.update(relpath.encode())
                h.update(hashlib.sha1(f.read_bytes()).hexdigest().encode())
            except OSError:
                continue
        return h.hexdigest()
    except Exception:
        h = hashlib.sha1()
        for f in iter_source_files(root):
            try:
                rel = f.relative_to(root)
                h.update(str(rel).encode())
                h.update(hashlib.sha1(f.read_bytes()).hexdigest().encode())
            except OSError:
                continue
        return h.hexdigest()


def stamp(root: Path, kind: str, exit_code: int, cmd: list[str]) -> dict:
    """Record that ``kind`` (tests/build/lint/typecheck) just ran."""
    root = Path(root)
    # Create .proofloop/ BEFORE computing the digest so the untracked-dir
    # entry in `git status` is identical now and at gate time.
    session_path(root).parent.mkdir(parents=True, exist_ok=True)
    data = load_session(root)
    data[kind] = {
        "ran_at": now_iso(),
        "exit_code": exit_code,
        "cmd": list(cmd),
        "worktree_digest": worktree_digest(root),
    }
    path = session_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".session-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return data[kind]


def marker_status(session: dict, kind: str, current_digest: str) -> tuple[str, dict | None]:
    """Classify a session marker.

    Returns one of: ``missing``, ``stale_age``, ``stale_digest``,
    ``failed``, ``fresh`` — plus the marker itself (or None).
    """
    marker = session.get(kind)
    if not isinstance(marker, dict):
        return "missing", None
    try:
        ran_at = datetime.fromisoformat(str(marker.get("ran_at", "")).replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - ran_at).total_seconds() / 3600
    except Exception:
        return "missing", marker
    if age_hours > MAX_MARKER_AGE_HOURS:
        return "stale_age", marker
    if marker.get("worktree_digest") != current_digest:
        return "stale_digest", marker
    if marker.get("exit_code", 1) != 0:
        return "failed", marker
    return "fresh", marker

"""Shared git-diff plumbing for the diff-scoped checks.

Same discipline as ``secrets.gitignored_paths``: one subprocess call with a
timeout, and any failure (not a git repo, no commits yet, git missing)
returns None so callers SKIP — never fail — outside a usable git context.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    return cp.stdout


def changed_paths(root: Path) -> list[str] | None:
    """Repo-relative paths with uncommitted changes — staged, unstaged, AND
    untracked (a new migration file is usually untracked). None outside a
    git repo."""
    status = _git(root, "status", "--porcelain")
    if status is None:
        return None
    paths: list[str] = []
    for line in status.splitlines():
        if len(line) <= 3:
            continue
        path = line[3:].strip()
        if " -> " in path:  # rename: old -> new; the new path is the change
            path = path.split(" -> ")[-1]
        paths.append(path.strip('"'))
    return paths


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(root: Path) -> list[tuple[str, int, str]] | None:
    """(file, new_lineno, text) for every line ADDED in the uncommitted diff
    of tracked files (``git diff HEAD -U0``). None when there is no HEAD to
    diff against (fresh repo) or not a git repo."""
    diff = _git(root, "diff", "HEAD", "-U0", "--no-color")
    if diff is None:
        return None
    out: list[tuple[str, int, str]] = []
    current_file: str | None = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            current_file = None if path == "/dev/null" else path.removeprefix("b/")
            continue
        match = _HUNK_RE.match(line)
        if match:
            lineno = int(match.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if current_file is not None:
                out.append((current_file, lineno, line[1:]))
            lineno += 1
    return out

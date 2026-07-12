"""Context / trace capture for a gate run.

Lightweight by design: repo identity, git state, a bounded diff excerpt,
the source file list the checks will scan, the driving agent, and an
environment *fingerprint* (variable NAMES only — values never leave the
process; see the scrub invariant in gate.py).
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .agent_detect import detect_agent_source

DIFF_EXCERPT_MAX_LINES = 200

EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".proofjury",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".next",
    "dist",
}


@dataclass
class RunContext:
    repo_id: str
    branch: str | None
    head_sha: str | None
    dirty: bool
    changed_files: list[str] = field(default_factory=list)
    diff_excerpt: str = ""
    files: list[Path] = field(default_factory=list)
    agent_source: str = "unknown"
    env_fingerprint: list[str] = field(default_factory=list)


def iter_source_files(root: Path) -> list[Path]:
    """All project files under ``root``, pruning vendored/derived dirs."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")
        )
        for fn in sorted(filenames):
            if fn == ".DS_Store":
                continue
            out.append(Path(dirpath) / fn)
    return sorted(out)


def load_config(root: Path) -> dict:
    """Parse ``.proofjury.toml`` if present; never raise."""
    path = root / ".proofjury.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


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


def _derive_repo_id(root: Path) -> str:
    url = _git(root, "remote", "get-url", "origin")
    if url:
        slug = url.strip()
        slug = slug.removesuffix(".git")
        # ssh form: git@github.com:owner/repo — take after the colon
        if ":" in slug and "://" not in slug:
            slug = slug.rsplit(":", 1)[-1]
        parts = [p for p in slug.replace("\\", "/").split("/") if p]
        if len(parts) >= 2:
            return "/".join(parts[-2:])
        if parts:
            return parts[-1]
    return root.name


def resolve_repo_id(root: Path) -> str:
    """Stable repo identity across remote changes.

    Derived once (origin slug, else directory name) and persisted in
    ``.proofjury/repo_id`` on the first gate run; read back thereafter,
    so adding/removing the origin remote never orphans prior memory
    records for recall.
    """
    path = Path(root) / ".proofjury" / "repo_id"
    try:
        cached = path.read_text().strip()
        if cached:
            return cached
    except OSError:
        pass
    repo_id = _derive_repo_id(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(repo_id + "\n")
    except OSError:
        pass  # persistence is best-effort; the derived id still works
    return repo_id


def capture_context(root: Path, env: Mapping[str, str]) -> RunContext:
    root = Path(root)
    status = _git(root, "status", "--porcelain")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(root, "rev-parse", "--short", "HEAD")
    diff = _git(root, "diff") or ""
    diff_lines = diff.splitlines()
    excerpt = "\n".join(diff_lines[:DIFF_EXCERPT_MAX_LINES])
    if len(diff_lines) > DIFF_EXCERPT_MAX_LINES:
        excerpt += f"\n… (+{len(diff_lines) - DIFF_EXCERPT_MAX_LINES} more diff lines truncated)"
    changed = []
    if status:
        for line in status.splitlines():
            if len(line) > 3:
                changed.append(line[3:].strip())
    return RunContext(
        repo_id=resolve_repo_id(root),
        branch=branch.strip() if branch else None,
        head_sha=head.strip() if head else None,
        dirty=bool(status and status.strip()),
        changed_files=changed,
        diff_excerpt=excerpt,
        files=iter_source_files(root),
        agent_source=detect_agent_source(env),
        env_fingerprint=sorted(env.keys()),
    )


def git_summary(ctx: RunContext) -> str:
    """Human/judge-facing one-block summary of the repo state."""
    if ctx.branch is None and ctx.head_sha is None:
        head = "not a git repository"
    else:
        head = f"branch {ctx.branch or '?'} @ {ctx.head_sha or '?'} ({'dirty' if ctx.dirty else 'clean'})"
    lines = [head]
    if ctx.changed_files:
        shown = ", ".join(ctx.changed_files[:10])
        more = f" (+{len(ctx.changed_files) - 10} more)" if len(ctx.changed_files) > 10 else ""
        lines.append(f"changed files: {shown}{more}")
    if ctx.diff_excerpt:
        lines.append("--- diff excerpt ---")
        lines.append(ctx.diff_excerpt)
    return "\n".join(lines)

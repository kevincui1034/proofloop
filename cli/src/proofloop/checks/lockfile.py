"""lockfile_drift — a dependency manifest changed but its lockfile didn't.

Deploying installs from the stale lockfile (or fails resolution), so the
running app doesn't match the manifest the code was written against. Fires
only when a lockfile already EXISTS in the repo — a project that doesn't
commit lockfiles is skipped, not nagged. A manifest edit that touches only
non-dependency keys (e.g. scripts) still fires; label it false_positive —
that is the correction loop, not a parser.

Skipped outside a git repo or when no manifest changed.
"""

from __future__ import annotations

from .base import CheckContext, CheckResult, Evidence, register
from .diffbase import changed_paths

#: manifest filename → its possible lockfiles (first existing one applies).
_LOCK_PAIRS: dict[str, list[str]] = {
    "package.json": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"],
    "pyproject.toml": ["uv.lock", "poetry.lock"],
    "Cargo.toml": ["Cargo.lock"],
    "Gemfile": ["Gemfile.lock"],
}


@register
def check_lockfile(ctx: CheckContext) -> CheckResult:
    changed = changed_paths(ctx.root)
    if changed is None:
        return CheckResult(name="lockfile", passed=True, skipped=True)
    changed_set = set(changed)

    evidence: list[Evidence] = []
    applicable = False
    for manifest, lock_names in _LOCK_PAIRS.items():
        # Check the repo root and any changed manifest deeper in the tree
        # (monorepo workspaces) — the lockfile is looked up beside it.
        manifest_paths = {p for p in changed_set if p == manifest or p.endswith("/" + manifest)}
        for manifest_path in manifest_paths:
            prefix = manifest_path.rsplit("/", 1)[0] + "/" if "/" in manifest_path else ""
            locks = [
                f"{prefix}{name}"
                for name in lock_names
                if (ctx.root / f"{prefix}{name}").exists()
            ]
            if not locks:
                continue  # not a lockfile-managed manifest — out of scope
            applicable = True
            if not any(lock in changed_set for lock in locks):
                evidence.append(
                    Evidence(
                        file=manifest_path,
                        line=1,
                        detail=f"changed without {locks[0]}",
                    )
                )
    if not applicable:
        return CheckResult(name="lockfile", passed=True, skipped=True)
    if not evidence:
        return CheckResult(name="lockfile", passed=True)
    return CheckResult(
        name="lockfile",
        passed=False,
        failure_class="lockfile_drift",
        evidence=evidence,
        fix_hint=(
            "Update the lockfile to match the manifest (e.g. `npm install` / "
            "`uv lock`) and include it in the change."
        ),
    )

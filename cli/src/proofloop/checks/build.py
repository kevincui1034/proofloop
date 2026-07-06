"""build_failure — the build must have run (and passed) for this worktree.

Uses the same session-marker mechanism as the tests check, for kind
"build". Builds are never run inline by the gate — the marker comes
from ``proofloop run build -- <cmd>``. If the project has no build step
(no package.json build script AND no [commands].build in
.proofloop.toml) the check is skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import CheckContext, CheckResult, Evidence, register
from ..session import marker_status

SESSION_FILE = ".proofloop/session.json"


def _package_json_script(root: Path, script: str) -> bool:
    pkg = root / "package.json"
    if not pkg.is_file():
        return False
    try:
        data = json.loads(pkg.read_text())
    except Exception:
        return False
    return isinstance(data.get("scripts"), dict) and script in data["scripts"]


def build_applicable(ctx: CheckContext) -> tuple[bool, str]:
    """Whether a build step exists, and the suggested build command."""
    configured = (ctx.config.get("commands") or {}).get("build")
    if configured:
        return True, str(configured)
    if _package_json_script(ctx.root, "build"):
        return True, "npm run build"
    return False, ""


@register
def check_build(ctx: CheckContext) -> CheckResult:
    applicable, suggested = build_applicable(ctx)
    if not applicable:
        return CheckResult(name="build", passed=True, skipped=True)

    fix_hint = f"Run: proofloop run build -- {suggested}"
    status, marker = marker_status(ctx.session, "build", ctx.digest)
    if status == "fresh":
        return CheckResult(name="build", passed=True)

    details = {
        "missing": "no build recorded for this worktree",
        "stale_age": "last recorded build is older than 24h",
        "stale_digest": "code changed since the last build (worktree digest mismatch)",
        "failed": (
            f"build failed with exit code {marker.get('exit_code')}"
            f" ({' '.join(marker.get('cmd', []))})"
            if marker
            else "build failed"
        ),
    }
    return CheckResult(
        name="build",
        passed=False,
        failure_class="build_failure",
        evidence=[Evidence(file=SESSION_FILE, line=1, detail=details.get(status, status))],
        fix_hint=fix_hint,
    )

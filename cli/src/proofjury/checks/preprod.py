"""preprod_check_skipped — lint/typecheck ran & passed for this worktree.

Same session-marker mechanism, kinds "lint" and "typecheck". A kind is
applicable when configured in .proofjury.toml [commands] or present as a
package.json script. Skipped entirely when neither kind is applicable.
"""

from __future__ import annotations

from .base import CheckContext, CheckResult, Evidence, register
from .build import _package_json_script
from ..session import marker_status

SESSION_FILE = ".proofjury/session.json"


def _applicable_kinds(ctx: CheckContext) -> dict[str, str]:
    """Map of applicable kind -> suggested command."""
    kinds: dict[str, str] = {}
    commands = ctx.config.get("commands") or {}
    for kind in ("lint", "typecheck"):
        configured = commands.get(kind)
        if configured:
            kinds[kind] = str(configured)
        elif _package_json_script(ctx.root, kind):
            kinds[kind] = f"npm run {kind}"
    return kinds


@register
def check_preprod(ctx: CheckContext) -> CheckResult:
    kinds = _applicable_kinds(ctx)
    if not kinds:
        return CheckResult(name="preprod", passed=True, skipped=True)

    details = {
        "missing": "not run for this worktree",
        "stale_age": "last run is older than 24h",
        "stale_digest": "code changed since it last ran",
    }
    evidence: list[Evidence] = []
    hints: list[str] = []
    for kind, suggested in kinds.items():
        status, marker = marker_status(ctx.session, kind, ctx.digest)
        if status == "fresh":
            continue
        if status == "failed":
            detail = f"{kind} failed with exit code {marker.get('exit_code')}" if marker else f"{kind} failed"
        else:
            detail = f"{kind} {details.get(status, status)}"
        evidence.append(Evidence(file=SESSION_FILE, line=1, detail=detail))
        hints.append(f"Run: proofjury run {kind} -- {suggested}")

    if not evidence:
        return CheckResult(name="preprod", passed=True)
    return CheckResult(
        name="preprod",
        passed=False,
        failure_class="preprod_check_skipped",
        evidence=evidence,
        fix_hint="; ".join(hints),
    )

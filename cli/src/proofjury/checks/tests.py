"""tests_not_run / test_failure — did tests run against THIS worktree?

Reads the session marker stamped by ``proofjury run tests -- <cmd>``.
Fails ``tests_not_run`` when the marker is absent, older than 24h, or
its worktree digest no longer matches (code changed since tests ran);
``test_failure`` when the recorded exit code is non-zero.
"""

from __future__ import annotations

from .base import CheckContext, CheckResult, Evidence, register
from ..session import marker_status

SESSION_FILE = ".proofjury/session.json"
FIX_HINT = "Run: proofjury run tests -- pytest"


@register
def check_tests(ctx: CheckContext) -> CheckResult:
    status, marker = marker_status(ctx.session, "tests", ctx.digest)
    if status == "fresh":
        return CheckResult(name="tests", passed=True)

    if status == "failed":
        code = marker.get("exit_code") if marker else "?"
        cmd = " ".join(marker.get("cmd", [])) if marker else ""
        return CheckResult(
            name="tests",
            passed=False,
            failure_class="test_failure",
            evidence=[
                Evidence(
                    file=SESSION_FILE,
                    line=1,
                    detail=f"test run failed with exit code {code} ({cmd})",
                )
            ],
            fix_hint=FIX_HINT,
        )

    details = {
        "missing": "no test run recorded for this worktree",
        "stale_age": "last recorded test run is older than 24h",
        "stale_digest": "code changed since tests last ran (worktree digest mismatch)",
    }
    return CheckResult(
        name="tests",
        passed=False,
        failure_class="tests_not_run",
        evidence=[Evidence(file=SESSION_FILE, line=1, detail=details.get(status, status))],
        fix_hint=FIX_HINT,
    )

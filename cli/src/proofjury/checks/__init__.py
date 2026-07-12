"""Deterministic readiness checks. Import order == execution order."""

from __future__ import annotations

from .base import (  # noqa: F401
    CheckContext,
    CheckResult,
    Evidence,
    REGISTRY,
    register,
)

# Importing the modules populates REGISTRY in this order.
from . import env_vars  # noqa: F401,E402
from . import tests  # noqa: F401,E402
from . import build  # noqa: F401,E402
from . import preprod  # noqa: F401,E402
from . import secrets  # noqa: F401,E402
from . import config  # noqa: F401,E402
from . import migrations  # noqa: F401,E402
from . import lockfile  # noqa: F401,E402
from . import unfinished  # noqa: F401,E402

#: Registered function → the CheckResult name it reports. Used to emit a
#: skipped placeholder (with the right name) for checks a profile excludes,
#: without evaluating them.
CHECK_NAMES: dict = {
    env_vars.check_env_vars: "env_vars",
    tests.check_tests: "tests",
    build.check_build: "build",
    preprod.check_preprod: "preprod",
    secrets.check_secrets: "secrets",
    config.check_config: "config",
    migrations.check_migrations: "migrations",
    lockfile.check_lockfile: "lockfile",
    unfinished.check_unfinished: "unfinished",
}

#: Built-in per-action check profiles. An action absent here runs ALL
#: checks (deploy and release deliberately have no profile). Merge is a
#: code-readiness moment: env/secrets/config are deploy-target concerns,
#: and migrations may deliberately merge before their deploy-time run —
#: but lockfile drift and unfinished work belong in the merge too.
DEFAULT_ACTION_PROFILES: dict[str, list[str]] = {
    "merge": ["tests", "build", "preprod", "lockfile", "unfinished"],
}


def resolve_check_profile(config: dict, action: str) -> set[str] | None:
    """Which check names evaluate for ``action`` (None = all).

    ``.proofjury.toml [actions.<action>] checks = [...]`` overrides the
    built-in default profile for that action.
    """
    actions_cfg = config.get("actions") or {}
    action_cfg = actions_cfg.get(action) or {}
    configured = action_cfg.get("checks")
    if isinstance(configured, list) and configured:
        return {str(name) for name in configured}
    default = DEFAULT_ACTION_PROFILES.get(action)
    return set(default) if default is not None else None


def run_checks(ctx: CheckContext, only: set[str] | None = None) -> list[CheckResult]:
    """Run the registry; checks outside ``only`` are emitted as skipped.

    Profile-skipped checks keep the record shape uniform (every record
    lists every check) and — like any skipped check — never count toward
    auto-resolution.
    """
    results: list[CheckResult] = []
    for fn in REGISTRY:
        name = CHECK_NAMES.get(fn)
        if only is not None and name is not None and name not in only:
            results.append(CheckResult(name=name, passed=True, skipped=True))
        else:
            results.append(fn(ctx))
    return results

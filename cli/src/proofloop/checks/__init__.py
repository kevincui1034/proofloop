"""Deterministic readiness checks. Import order == execution order."""

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


def run_checks(ctx: CheckContext) -> list[CheckResult]:
    return [fn(ctx) for fn in REGISTRY]

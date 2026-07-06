"""Check primitives: Evidence, CheckResult, and the ordered registry.

Every check in this layer is deterministic — NO LLM is ever consulted
for pass/fail. The LLM judge only *explains* failures afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping


@dataclass
class Evidence:
    """A file:line-anchored piece of proof for a finding."""

    file: str
    line: int
    detail: str


@dataclass
class CheckResult:
    name: str
    type: str = "deterministic"
    passed: bool = True
    skipped: bool = False
    failure_class: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    fix_hint: str | None = None
    # Optional suffix appended after the evidence list, e.g. "unset" →
    # "STRIPE_API_KEY (payments.py:14), DATABASE_URL (db.py:3) unset"
    evidence_suffix: str | None = None

    def evidence_str(self) -> str:
        parts = [f"{e.detail} ({e.file}:{e.line})" for e in self.evidence]
        rendered = ", ".join(parts)
        if rendered and self.evidence_suffix:
            rendered += f" {self.evidence_suffix}"
        return rendered


@dataclass
class CheckContext:
    """Everything a check may look at. Checks must not touch os.environ
    directly — ``env`` is the deploy context under test."""

    root: Path
    env: Mapping[str, str]
    config: dict
    files: list[Path]
    session: dict
    digest: str


CheckFunc = Callable[[CheckContext], CheckResult]

#: Ordered check registry — populated at import time by @register.
REGISTRY: list[CheckFunc] = []


def register(fn: CheckFunc) -> CheckFunc:
    REGISTRY.append(fn)
    return fn


def rel(path: Path, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)

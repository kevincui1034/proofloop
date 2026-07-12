"""Advisory judge — model judgment that reviews, grounds in memory, and
NEVER blocks.

Second surface, one authority: deterministic checks alone set
``blocked``/``exit_code``; the advisory judge reviews the change for
tier-4/5 risks (bad engineering / not what was asked) that a
deterministic checklist structurally cannot enumerate, plus adjudication
notes on existing deterministic failures ("likely a false positive —
prior chk_042 with this shape was labeled false_positive"). Findings are
recorded and (conditionally) surfaced as *context*; they never touch the
decision path.

Best-effort / offline-first: any exception or timeout yields zero
findings and the record is byte-identical to a run without the judge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from .. import config as config_module
from ..checks.base import CheckResult
from ..memory.schema import MemoryRecord
from ._openai_compat import _FENCE_RE
from .anthropic_direct import AnthropicJudge
from .openai_direct import OpenAIJudge
from .openrouter import OpenRouterJudge

KINDS = ("discovery", "adjudication")
TIERS = (4, 5)

ADVISORY_SYSTEM_PROMPT = (
    "You are Proofjury's advisory reviewer. Deterministic checks have already "
    "decided pass/fail — you CANNOT block and must not try. You review the "
    "change for risks the deterministic checklist cannot enumerate, grounded "
    "in this repo's memory of past outcomes. Emit two kinds of finding: "
    '"discovery" — a genuine tier-4 (bad engineering: silent failure modes, '
    "missing error handling on external calls, data-loss risk) or tier-5 "
    "(the change does not match the stated task) risk in THIS diff; "
    '"adjudication" — a note on a listed deterministic FAILURE, e.g. that it '
    "is likely a false positive given a labeled prior. Cite prior record ids "
    'in grounded_in when they informed a finding. Never re-raise a concern '
    "listed as previously rejected. Only flag what is visible in the diff or "
    "check results — no speculation; an empty findings list is a good answer. "
    'Respond as strict JSON: {"findings": [{"concern": "<1-2 sentences>", '
    '"kind": "discovery"|"adjudication", "tier": 4|5, "confidence": <0.0-1.0>, '
    '"grounded_in": ["<prior record id>", ...], "target": "<file:line>"|null}]}.'
)


@dataclass
class AdvisoryFinding:
    concern: str
    kind: str  # "discovery" | "adjudication"
    tier: int  # 4 | 5
    confidence: float
    grounded_in: list[str] = field(default_factory=list)
    target: str | None = None


@dataclass
class AdvisoryOutput:
    findings: list[AdvisoryFinding]
    model_id: str
    cost_usd: float = 0.0
    raw: str = ""  # the verbatim model reply → persisted advisory_output


@dataclass
class AdvisoryInput:
    """Everything the advisory judge sees. ``to_prompt_text()`` is THE
    persisted ``advisory_input`` — training feature and runtime prompt
    are the same string, exactly like ``JudgeInput``."""

    action: str
    repo_id: str
    task_ref: str | None
    git_summary: str
    results: list[CheckResult] = field(default_factory=list)
    priors: list[MemoryRecord] = field(default_factory=list)
    rejected_concerns: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = [
            f"Proofjury advisory review — action: {self.action}",
            f"Repo: {self.repo_id}",
            f"Task: {self.task_ref or '(unknown — do not emit tier-5 findings)'}",
            "",
            "Deterministic check results (already decided — context only):",
        ]
        for result in self.results:
            if result.skipped:
                lines.append(f"- {result.name}: skipped")
            elif result.passed:
                lines.append(f"- {result.name}: passed")
            else:
                lines.append(
                    f"- {result.name}: FAILED [{result.failure_class}]: "
                    f"{result.evidence_str()}"
                )
        lines += ["", "Git summary:", self.git_summary or "(unavailable)", ""]
        lines.append("Prior records in this repo (with outcome labels):")
        if self.priors:
            for prior in self.priors:
                lines.append(f"- {_prior_line(prior)}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("Previously rejected advisories — do NOT re-raise:")
        if self.rejected_concerns:
            for concern in self.rejected_concerns:
                lines.append(f"- {concern}")
        else:
            lines.append("- none")
        lines += [
            "",
            "Review the change. Findings are advisory context only — the "
            "gate decision is already made.",
        ]
        return "\n".join(lines)


def _prior_line(prior: MemoryRecord) -> str:
    verdict = "passed" if prior.gate_passed else "blocked"
    classes = ", ".join(sorted(prior.failure_classes())) or "-"
    status = (prior.resolution or {}).get("status") or "unlabeled"
    bits = [f"{prior.id} ({prior.created_at}) {verdict} [{classes}] resolution={status}"]
    if prior.resolves:
        bits.append(f"resolves={prior.resolves}")
    for entry in prior.advisories:
        if entry.get("label"):
            bits.append(
                f'advisory {entry.get("id")} "{entry.get("concern")}" '
                f'label={entry.get("label")}'
            )
    return " · ".join(bits)


@runtime_checkable
class AdvisoryJudge(Protocol):
    def review(self, advisory_input: AdvisoryInput) -> AdvisoryOutput:  # pragma: no cover
        ...


def parse_findings(content: str, known_ids: set[str]) -> list[AdvisoryFinding]:
    """Strict-JSON parse of the model reply; malformed findings dropped.

    Structural validation only — policy (tier mutes, task gating,
    max_findings, rejected-signature suppression, confidence delivery)
    lives in the gate. ``grounded_in`` is filtered to ids the prompt
    actually offered, so a hallucinated citation never enters a record.
    """
    text = _FENCE_RE.sub("", (content or "").strip()).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        return []
    findings: list[AdvisoryFinding] = []
    for item in parsed["findings"]:
        if not isinstance(item, dict):
            continue
        concern = item.get("concern")
        kind = item.get("kind")
        tier = item.get("tier")
        confidence = item.get("confidence")
        if not isinstance(concern, str) or not concern.strip():
            continue
        if kind not in KINDS or tier not in TIERS:
            continue
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            continue
        grounded = item.get("grounded_in")
        grounded_in = [
            g for g in grounded if isinstance(g, str) and g in known_ids
        ] if isinstance(grounded, list) else []
        target = item.get("target")
        if not isinstance(target, str) or not target.strip():
            target = None
        findings.append(
            AdvisoryFinding(
                concern=" ".join(concern.split()),
                kind=kind,
                tier=tier,
                confidence=min(1.0, max(0.0, float(confidence))),
                grounded_in=grounded_in,
                target=target,
            )
        )
    return findings


class _ChatAdvisoryMixin:
    """``review()`` on top of an adapter's ``_chat()`` transport.

    Best-effort: ANY exception (network, HTTP, missing content) → zero
    findings, model_id "none" — the gate proceeds as if no judge ran.
    """

    def review(self, advisory_input: AdvisoryInput) -> AdvisoryOutput:
        try:
            content, model_id, cost = self._chat(
                ADVISORY_SYSTEM_PROMPT, advisory_input.to_prompt_text()
            )
        except Exception:
            return AdvisoryOutput(findings=[], model_id="none", cost_usd=0.0, raw="")
        known_ids = {prior.id for prior in advisory_input.priors}
        return AdvisoryOutput(
            findings=parse_findings(content, known_ids),
            model_id=model_id,
            cost_usd=cost,
            raw=content,
        )


class OpenRouterAdvisoryJudge(_ChatAdvisoryMixin, OpenRouterJudge):
    pass


class OpenAIAdvisoryJudge(_ChatAdvisoryMixin, OpenAIJudge):
    pass


class AnthropicAdvisoryJudge(_ChatAdvisoryMixin, AnthropicJudge):
    pass


_ADAPTERS = {
    "openrouter": OpenRouterAdvisoryJudge,
    "anthropic": AnthropicAdvisoryJudge,
    "openai": OpenAIAdvisoryJudge,
}


def get_advisory_judge(
    env: Mapping[str, str] | None,
    root: Path | None,
    repo_config: dict | None,
) -> AdvisoryJudge | None:
    """Select an advisory judge, or None (unlike the diagnosis judge there
    is no deterministic fallback — no LLM simply means no advisories).

    ``[advisory].model`` overrides the judge's resolved model so the
    advisory surface can run a different (e.g. stronger) model than the
    explain-a-block judge.
    """
    settings = config_module.advisory_settings(repo_config)
    if not settings["enabled"]:
        return None
    resolved = config_module.resolve_judge(env)
    if resolved is None:
        return None
    adapter = _ADAPTERS.get(resolved["provider"])
    if adapter is None:
        return None
    return adapter(
        api_key=resolved["api_key"],
        model=settings["model"] or resolved["model"],
        root=root,
    )

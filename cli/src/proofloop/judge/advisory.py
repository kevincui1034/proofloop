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
ADVISORY_RUBRIC_KEYS = (
    "visible_in_diff",
    "has_specific_target",
    "grounded_in_labeled_prior",
    "matches_prior_pattern",
    "references_failed_check_for_adjudication",
    "concern_is_concrete_and_actionable",
    "depends_on_missing_context",
    "weak_or_generic_language",
    "multi_hop_speculation",
    "contradicted_by_rejected_signature",
    "purely_speculative_claim",
)
ADVISORY_RUBRIC_WEIGHTS = {
    "visible_in_diff": 0.30,
    "has_specific_target": 0.10,
    "grounded_in_labeled_prior": 0.20,
    "matches_prior_pattern": 0.10,
    "references_failed_check_for_adjudication": 0.15,
    "concern_is_concrete_and_actionable": 0.10,
    "depends_on_missing_context": -0.20,
    "weak_or_generic_language": -0.15,
    "multi_hop_speculation": -0.25,
}
ADVISORY_RUBRIC_VETOES = (
    "contradicted_by_rejected_signature",
    "purely_speculative_claim",
)

ADVISORY_SYSTEM_PROMPT = (
    "You are Proofloop's advisory reviewer. Deterministic checks have already "
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
    '"kind": "discovery"|"adjudication", "tier": 4|5, '
    '"rubric": {"visible_in_diff": true|false, "has_specific_target": true|false, '
    '"grounded_in_labeled_prior": true|false, "matches_prior_pattern": true|false, '
    '"references_failed_check_for_adjudication": true|false, '
    '"concern_is_concrete_and_actionable": true|false, '
    '"depends_on_missing_context": true|false, "weak_or_generic_language": true|false, '
    '"multi_hop_speculation": true|false, "contradicted_by_rejected_signature": true|false, '
    '"purely_speculative_claim": true|false}, '
    '"model_confidence": <0.0-1.0 optional, analysis only>, '
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
    rubric: dict[str, bool] | None = None
    model_confidence: float | None = None


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
            f"Proofloop advisory review — action: {self.action}",
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
        if not isinstance(concern, str) or not concern.strip():
            continue
        if kind not in KINDS or tier not in TIERS:
            continue
        rubric = _parse_rubric(item.get("rubric"))
        model_confidence = _parse_confidence(
            item.get("model_confidence", item.get("confidence"))
        )
        if rubric is None:
            confidence = _parse_confidence(item.get("confidence"))
            if confidence is None:
                continue
        else:
            confidence = compute_advisory_confidence(rubric)
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
                confidence=confidence,
                grounded_in=grounded_in,
                target=target,
                rubric=rubric,
                model_confidence=model_confidence,
            )
        )
    return findings


def _parse_confidence(value) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return min(1.0, max(0.0, float(value)))


def _parse_rubric(value) -> dict[str, bool] | None:
    if not isinstance(value, dict):
        return None
    return {
        key: value.get(key, False)
        if isinstance(value.get(key, False), bool)
        else False
        for key in ADVISORY_RUBRIC_KEYS
    }


def compute_advisory_confidence(rubric: dict[str, bool]) -> float:
    """Score fixed advisory rubric facts without trusting a model scalar."""
    if any(rubric.get(key, False) for key in ADVISORY_RUBRIC_VETOES):
        return 0.0
    score = 0.0
    for key, weight in ADVISORY_RUBRIC_WEIGHTS.items():
        if rubric.get(key, False):
            score += weight
    return min(1.0, max(0.0, score))


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

"""Gate orchestration: check → recall → judge → record → block/allow.

Invariants:
- A blocked run NEVER spawns the guarded command.
- BOTH passing and failing runs are recorded (gate_passed distinguishes).
- Recall happens BEFORE the judge so the judge can cite priors; a strong
  recurrence match is cited deterministically — no model call.
- Env var VALUES of 8+ characters are scrubbed from all persisted output
  (records, proof files, run logs); shorter values are not scrubbed —
  they collide with ordinary text.
- Internal errors must never silently allow (callers exit 3).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from . import __version__, ux
from .checks import CheckContext, CheckResult, resolve_check_profile, run_checks
from .config import advisory_settings, cross_repo_enabled, llm_configured
from .context import capture_context, git_summary, load_config
from .judge import DeterministicJudge, JudgeInput, JudgeOutput, get_judge
from .judge.advisory import AdvisoryFinding, AdvisoryInput, get_advisory_judge
from .judge.deterministic import compile_fix_steps
from .memory.recall import (
    advisory_signature,
    is_foreign_prior,
    recall,
    rejected_advisory_signatures,
    strong_match,
)
from .memory.registry import foreign_stores, register_store
from .memory.schema import MemoryRecord
from .memory.store import MemoryStore
from .session import load_session, now_iso, worktree_digest

EXIT_BLOCKED = 2
EXIT_INTERNAL_ERROR = 3

MIN_SCRUB_LENGTH = 8
REDACTED = "[REDACTED]"

#: task_ref is intent context (names only, scrubbed) — keep it bounded.
TASK_REF_MAX_CHARS = 400

# Env vars whose values are ambient context (paths, locale, terminal), not
# credentials. Scrubbing these would redact $HOME/$PWD out of every path in
# the proof record without protecting a secret. Name-based and conservative:
# anything not listed here is still scrubbed by value.
SAFE_ENV_NAMES = frozenset({
    "_",  # POSIX shells: path of the last executed command
    "PWD", "OLDPWD", "HOME", "PATH", "TMPDIR", "SHELL", "SHLVL", "TERM",
    "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "TERM_SESSION_ID", "USER",
    "LOGNAME", "LANG", "LANGUAGE", "EDITOR", "VISUAL", "PAGER", "COLORTERM",
    "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH", "NODE_PATH", "DISPLAY",
    "XPC_SERVICE_NAME", "XPC_FLAGS", "__CF_USER_TEXT_ENCODING",
    "COMMAND_MODE", "SSH_AUTH_SOCK", "Apple_PubSub_Socket_Render",
})
SAFE_ENV_PREFIXES = ("LC_", "XDG_", "HOMEBREW_", "PYENV_", "NVM_")


def _is_safe_env_name(name: str) -> bool:
    return name in SAFE_ENV_NAMES or name.startswith(SAFE_ENV_PREFIXES)


@dataclass
class GateResult:
    record: MemoryRecord
    results: list[CheckResult]
    failures: list[CheckResult]
    blocked: bool
    exit_code: int
    recalled: MemoryRecord | None
    #: Advisory context to deliver to the coding agent this event —
    #: injected findings plus drained (approved/retraction) notes.
    #: Context only: never a permission decision.
    agent_notes: list[str] = field(default_factory=list)


def scrub_text(text: str, env: Mapping[str, str]) -> str:
    """Replace any current env VALUE (>= 8 chars) with [REDACTED].

    Also matches the JSON-escaped form of each value (quotes, backslashes,
    newlines escaped) so values survive neither in plain text nor inside
    already-serialized JSON. Ambient non-credential vars (SAFE_ENV_NAMES,
    e.g. PWD/HOME/PATH) are exempt so paths stay readable in proof records.
    """
    if not text:
        return text
    values = {
        v
        for k, v in env.items()
        if isinstance(v, str)
        and len(v) >= MIN_SCRUB_LENGTH
        and not _is_safe_env_name(k)
    }
    needles: set[str] = set()
    for value in values:
        needles.add(value)
        escaped = json.dumps(value, ensure_ascii=False)[1:-1]
        if escaped != value:
            needles.add(escaped)
    for needle in sorted(needles, key=len, reverse=True):
        if needle in text:
            text = text.replace(needle, REDACTED)
    return text


def _scrub_results(results: list[CheckResult], env: Mapping[str, str]) -> None:
    for result in results:
        for evidence in result.evidence:
            evidence.detail = scrub_text(evidence.detail, env)
        if result.fix_hint:
            result.fix_hint = scrub_text(result.fix_hint, env)


def _inputs_hash(action: str, digest: str, files: list[Path], root: Path, env_names: list[str]) -> str:
    payload = json.dumps(
        {
            "action": action,
            "worktree_digest": digest,
            "files": sorted(str(f.relative_to(root)) if f.is_relative_to(root) else str(f) for f in files),
            "env_names": sorted(env_names),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def resolve_task_ref(
    explicit: str | None, env: Mapping[str, str], config: dict
) -> str | None:
    """What the agent was asked to do, when knowable (enables tier-5
    advisory findings). Opportunistic: explicit (hook transcript / --task)
    → ``PROOFJURY_TASK`` → ``[session].task`` in .proofjury.toml → None.
    """
    task = explicit or env.get("PROOFJURY_TASK")
    if not task:
        session_cfg = config.get("session")
        if isinstance(session_cfg, dict):
            value = session_cfg.get("task")
            if isinstance(value, str):
                task = value
    if not task or not str(task).strip():
        return None
    return " ".join(str(task).split())[:TASK_REF_MAX_CHARS]


def _find_resolvable_priors(
    store: MemoryStore, repo_id: str, results: list[CheckResult]
) -> list[MemoryRecord]:
    """ALL blocked + unresolved records in this repo whose failed checks
    all pass (verified, not skipped) in the current run.

    Called only when the current run PASSED. Every one of them gets an
    auto_resolved resolution; ``resolves`` cites the most recent so no
    earlier record from the same episode is orphaned.
    """
    passing = {r.name for r in results if r.passed and not r.skipped}
    priors: list[MemoryRecord] = []
    for record in store.iter_records():
        if record.repo_id != repo_id or record.gate_passed:
            continue
        if record.resolution is not None:
            continue
        failed = record.failed_checks()
        if failed and all(c.get("name") in passing for c in failed):
            priors.append(record)  # file order == chronological
    return priors


# --------------------------------------------------------------------------
# Advisory surface (step 3.5) — model judgment that NEVER touches the
# block/allow decision. Every helper here is firewalled behind run_gate's
# try/except: a broken advisory path degrades to zero findings.
# --------------------------------------------------------------------------


def _diff_lines(diff_excerpt: str) -> int:
    return sum(1 for line in diff_excerpt.splitlines() if line.strip())


def _advisory_cache_hit(store: MemoryStore, repo_id: str, inputs_hash: str) -> bool:
    """True when the advisory judge already reviewed these exact inputs
    (same ``inputs_hash``, non-empty ``advisory_output``) — re-running the
    model on an unchanged worktree buys nothing."""
    if not inputs_hash:
        return False
    for record in store.iter_records():
        if (
            record.repo_id == repo_id
            and record.inputs_hash == inputs_hash
            and record.advisory_output
        ):
            return True
    return False


def _advisory_priors(
    store: MemoryStore,
    repo_id: str,
    recall_priors: list[MemoryRecord],
    limit: int = 5,
) -> list[MemoryRecord]:
    """Priors for advisory grounding: the recall matches first (they share
    failure shape with this run), topped up with the repo's most recent
    *labeled* records — outcome labels are what makes memory
    decision-bearing for the judge."""
    chosen = list(recall_priors[:3])
    seen = {record.id for record in chosen}
    labeled: list[MemoryRecord] = []
    for record in store.iter_records():  # file order == chronological
        if record.repo_id != repo_id or record.id in seen:
            continue
        if record.resolution is not None or any(
            entry.get("label") for entry in record.advisories
        ):
            labeled.append(record)
    for record in reversed(labeled):  # most recent first
        if len(chosen) >= limit:
            break
        chosen.append(record)
        seen.add(record.id)
    return chosen


def _advisory_note(entry: dict, approved: bool = False) -> str:
    """One agent-facing context line for an advisory finding."""
    origin = "human-approved advisory" if approved else "advisory"
    note = (
        f"⚠ Proofjury {origin} {entry['id']} (model judgment, NOT blocking; "
        f"tier {entry['tier']}, confidence {entry['confidence']:.2f}): "
        f"{entry['concern']}"
    )
    if entry.get("target"):
        note += f" [{entry['target']}]"
    if entry.get("grounded_in"):
        note += f" (grounded in {', '.join(entry['grounded_in'])})"
    return note


def _retraction_note(entry: dict) -> str:
    return (
        f"Disregard advisory {entry['id']} — a human reviewed and rejected "
        f"it: {entry['concern']}"
    )


def _classify_advisories(
    findings: list[AdvisoryFinding],
    settings: dict,
    record_id: str,
    model_id: str,
    task_ref: str | None,
    rejected_signatures: set[str],
    scrub,
) -> tuple[list[dict], list[str]]:
    """Apply advisory policy → (record entries, agent notes to inject).

    Policy: muted tiers dropped; tier-5 needs a task_ref (no stated intent
    → nothing to judge intent against); human-rejected signatures never
    re-fire; then max_findings and the confidence gates decide delivery —
    injected (≥ auto) / held (≥ hold) / suppressed (noise floor, recorded
    only). Entry key order matches ADVISORY_ENTRY_KEYS (pinned).
    """
    kept = [
        finding
        for finding in findings
        if finding.tier in settings["tiers"]
        and (finding.tier != 5 or task_ref)
        and advisory_signature(finding.concern, finding.target)
        not in rejected_signatures
    ]
    entries: list[dict] = []
    notes: list[str] = []
    for index, finding in enumerate(kept[: settings["max_findings"]]):
        if finding.confidence >= settings["auto_inject_min_confidence"]:
            delivery = "injected"
        elif finding.confidence >= settings["hold_min_confidence"]:
            delivery = "held"
        else:
            delivery = "suppressed"
        entry = {
            "id": f"{record_id}#{index}",
            "concern": scrub(finding.concern),
            "kind": finding.kind,
            "tier": finding.tier,
            "confidence": round(finding.confidence, 3),
            "grounded_in": finding.grounded_in,
            "target": scrub(finding.target) if finding.target else None,
            "judge_model_id": model_id,
            "delivery": delivery,
            "label": None,
            "retraction": None,
        }
        entries.append(entry)
        if delivery == "injected":
            notes.append(_advisory_note(entry))
    return entries, notes


def _drain_pending_notes(
    store: MemoryStore, repo_id: str
) -> tuple[list[str], list[tuple[str, int, dict]]]:
    """Staged agent-notes from prior events: human-approved advisories and
    staged retractions. Returns (notes, updates); the caller applies the
    updates AFTER delivering so a crash re-delivers rather than drops."""
    notes: list[str] = []
    updates: list[tuple[str, int, dict]] = []
    for record in store.iter_records():
        if record.repo_id != repo_id:
            continue
        for index, entry in enumerate(record.advisories):
            if entry.get("delivery") == "staged" and entry.get("label") != "rejected":
                notes.append(_advisory_note(entry, approved=True))
                updates.append((record.id, index, {"delivery": "sent"}))
            if entry.get("retraction") == "staged":
                notes.append(_retraction_note(entry))
                updates.append((record.id, index, {"retraction": "sent"}))
    return notes, updates


def run_gate(
    root: Path,
    action: str,
    cmd: list[str] | None,
    *,
    force: bool = False,
    no_exec: bool = False,
    json_output: bool = False,
    env: Mapping[str, str] | None = None,
    deploy_env: Mapping[str, str] | None = None,
    judge=None,
    advisory_judge=None,
    task_ref: str | None = None,
    render: bool = True,
    console=None,
) -> GateResult:
    started = time.monotonic()
    root = Path(root).resolve()
    env = dict(os.environ) if env is None else dict(env)
    # Three distinct environments (do not conflate):
    # - check_env: what checks evaluate against — the deploy target's env
    #   when deploy_env is given (--env-file / [env].file), else the
    #   developer's env (today's behavior, bit-identical).
    # - env: what the child command is spawned with — always the
    #   developer's real environment (the deploy CLI needs PATH/HOME/auth).
    # - scrub_env: what persisted output is redacted against — the UNION;
    #   env-file values are deploy secrets and must be scrubbed too.
    check_env = dict(deploy_env) if deploy_env is not None else env
    scrub_env = {**env, **(deploy_env or {})}

    proof_root = root / ".proofjury"
    proof_root.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(proof_root)
    record_id = store.next_id()

    # 1. Context / trace capture
    run_context = capture_context(root, env)
    if deploy_env is not None:
        # Fingerprint the env the checks actually evaluated (names only).
        run_context.env_fingerprint = sorted(deploy_env.keys())
    config = load_config(root)
    cross_repo = cross_repo_enabled(config, env)
    try:
        # User-level registry: how other repos' gates find this store
        # (and vice versa). Best-effort — never fails the gate. Opted-out
        # repos deregister, so they are neither readers nor read.
        register_store(proof_root, run_context.repo_id, env, enabled=cross_repo)
    except Exception:
        pass
    digest = worktree_digest(root)
    session = load_session(root)
    task_ref = resolve_task_ref(task_ref, env, config)
    if task_ref:
        task_ref = scrub_text(task_ref, scrub_env)

    # 2. Deterministic checks (never LLM)
    check_context = CheckContext(
        root=root,
        env=check_env,
        config=config,
        files=run_context.files,
        session=session,
        digest=digest,
    )
    results = run_checks(check_context, only=resolve_check_profile(config, action))
    _scrub_results(results, scrub_env)
    failures = [r for r in results if not r.passed]

    # 3. Recall priors BEFORE judging, so the judge cites them
    foreign: list = []
    if failures and cross_repo:
        try:
            foreign = foreign_stores(proof_root, env)
        except Exception:
            foreign = []
    priors = (
        recall(store, run_context.repo_id, failures, foreign=foreign)
        if failures
        else []
    )
    recalled = priors[0] if priors else None
    summary = scrub_text(git_summary(run_context), scrub_env)
    inputs_hash = _inputs_hash(
        action, digest, run_context.files, root, run_context.env_fingerprint
    )

    # 3.5 Advisory judge — model judgment, advisory ONLY. Best-effort and
    #     fully firewalled: any failure here yields zero findings and the
    #     record is byte-identical to a run without the judge. Deterministic
    #     checks alone decide blocked/exit_code (steps 2 and 9).
    adv_settings = advisory_settings(config)
    advisories: list[dict] = []
    advisory_input_text = ""
    advisory_output_text = ""
    agent_notes: list[str] = []
    pending_updates: list[tuple[str, int, dict]] = []
    try:
        pending_notes, pending_updates = _drain_pending_notes(
            store, run_context.repo_id
        )
        agent_notes += pending_notes
    except Exception:
        pending_updates = []
    adv_engine = (
        advisory_judge
        if advisory_judge is not None
        else get_advisory_judge(env, proof_root, config)
    )
    if (
        adv_engine is not None
        and adv_settings["enabled"]
        and _diff_lines(run_context.diff_excerpt) >= adv_settings["diff_min_lines"]
        and not _advisory_cache_hit(store, run_context.repo_id, inputs_hash)
    ):
        try:
            rejected = rejected_advisory_signatures(store, run_context.repo_id)
            advisory_input = AdvisoryInput(
                action=action,
                repo_id=run_context.repo_id,
                task_ref=task_ref,
                git_summary=summary,
                results=results,
                priors=_advisory_priors(store, run_context.repo_id, priors),
                rejected_concerns=sorted(rejected.values()),
            )
            advisory_input_text = advisory_input.to_prompt_text()
            advisory_result = adv_engine.review(advisory_input)
            advisory_output_text = advisory_result.raw
            advisories, injected_notes = _classify_advisories(
                advisory_result.findings,
                adv_settings,
                record_id,
                advisory_result.model_id,
                task_ref,
                set(rejected),
                lambda text: scrub_text(text, scrub_env),
            )
            agent_notes += injected_notes
        except Exception:
            advisories, advisory_input_text, advisory_output_text = [], "", ""
    advisory_input_text = scrub_text(advisory_input_text, scrub_env)
    advisory_output_text = scrub_text(advisory_output_text, scrub_env)
    agent_notes = [scrub_text(note, scrub_env) for note in agent_notes]

    # 4. Judge (explanation only — pass/fail already decided above)
    judge_input = JudgeInput(
        action=action,
        repo_id=run_context.repo_id,
        failures=failures,
        git_summary=summary,
        priors=priors[:3],
    )
    if failures:
        if (
            recalled is not None
            and not is_foreign_prior(recalled)
            and strong_match(failures, recalled)
        ):
            # Known recurrence IN THIS REPO: cite the prior
            # deterministically — NO model call, even when an LLM judge
            # is configured. Foreign priors never short-circuit: their
            # file:line anchors describe another repo's tree.
            engine = DeterministicJudge()
        else:
            engine = judge if judge is not None else get_judge(env, proof_root)
        judge_output = engine.diagnose(judge_input)
    else:
        ran = sum(1 for r in results if not r.skipped)
        skipped = sum(1 for r in results if r.skipped)
        judge_output = JudgeOutput(
            diagnosis=f"All checks passed ({ran} run, {skipped} skipped). Clear to {action}.",
            fix_steps=[],
            model_id="none",
            cost_usd=0.0,
        )

    gate_passed = not failures
    blocked = bool(failures) and not force

    # 5. Auto-resolution linking: a passing run closes EVERY unresolved
    #    blocked record whose failed checks now pass (failure -> fix ->
    #    outcome triples); `resolves` cites the most recent one.
    resolves: str | None = None
    resolved_priors: list[MemoryRecord] = []
    if gate_passed:
        resolved_priors = _find_resolvable_priors(store, run_context.repo_id, results)
        if resolved_priors:
            resolves = resolved_priors[-1].id

    # 6. Proof files under the context ref — every payload field is
    #    scrubbed BEFORE serialization (values must not survive in
    #    JSON-escaped form), with a post-serialization scrub as belt
    #    and braces.
    run_dir = proof_root / "runs" / record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    checks_payload = [
        {
            "name": r.name,
            "type": r.type,
            "passed": r.passed,
            "skipped": r.skipped,
            "failure_class": r.failure_class,
            "evidence": [
                {"file": e.file, "line": e.line, "detail": e.detail} for e in r.evidence
            ],
            "fix_hint": r.fix_hint,
        }
        for r in results
    ]
    context_payload = {
        "repo_id": run_context.repo_id,
        "branch": scrub_text(run_context.branch, scrub_env) if run_context.branch else run_context.branch,
        "head_sha": run_context.head_sha,
        "dirty": run_context.dirty,
        "changed_files": [scrub_text(f, scrub_env) for f in run_context.changed_files],
        "agent_source": run_context.agent_source,
        "worktree_digest": digest,
        "env_fingerprint": run_context.env_fingerprint,  # names only, never values
        "cmd": [scrub_text(part, scrub_env) for part in cmd] if cmd else cmd,
        "action": action,
        "task_ref": task_ref,  # names/intent only; scrubbed above
    }
    (run_dir / "checks.json").write_text(
        scrub_text(json.dumps(checks_payload, indent=2, ensure_ascii=False), scrub_env),
        encoding="utf-8",
    )
    (run_dir / "context.json").write_text(
        scrub_text(json.dumps(context_payload, indent=2, ensure_ascii=False), scrub_env),
        encoding="utf-8",
    )
    (run_dir / "diff.patch").write_text(
        scrub_text(run_context.diff_excerpt, scrub_env), encoding="utf-8"
    )

    # 7. Build + persist the training-ready record (scrubbed)
    resolution = None
    if force and failures:
        resolution = {
            "status": "overridden",
            "note": "--force used; gate failures bypassed",
            "at": now_iso(),
        }
    record = MemoryRecord(
        id=record_id,
        repo_id=run_context.repo_id,
        created_at=now_iso(),
        action_intercepted=action,
        agent_source=run_context.agent_source,
        context_ref=f".proofjury/runs/{record_id}/",
        checks=[
            {
                "name": r.name,
                "type": r.type,
                "passed": r.passed,
                "failure_class": r.failure_class,
                "evidence": scrub_text(r.evidence_str(), scrub_env),
            }
            for r in results
        ],
        gate_passed=gate_passed,
        diagnosis=scrub_text(judge_output.diagnosis, scrub_env),
        judge_input=scrub_text(judge_input.to_prompt_text(), scrub_env),
        judge_output=scrub_text(
            json.dumps(
                {"diagnosis": judge_output.diagnosis, "fix_steps": judge_output.fix_steps},
                ensure_ascii=False,
            ),
            scrub_env,
        ),
        proof_refs=["checks.json", "context.json", "diff.patch"],
        recalled_from=recalled.id if recalled is not None else None,
        judge_model_id=judge_output.model_id,
        resolution=resolution,
        schema_version="1",
        cli_version=__version__,
        gate_duration_ms=int((time.monotonic() - started) * 1000),
        inputs_hash=inputs_hash,
        env_fingerprint=run_context.env_fingerprint,
        resolves=resolves,
        advisories=advisories,
        advisory_input=advisory_input_text,
        advisory_output=advisory_output_text,
        task_ref=task_ref,
    )
    store.append(record)
    store.append_markdown(record)
    for prior in resolved_priors:
        store.update_resolution(
            prior.id,
            {"status": "auto_resolved", "resolved_by": record_id, "at": now_iso()},
        )
    # Drained notes are now part of this event's delivery — mark them so
    # the next event doesn't repeat them.
    for prior_id, index, fields in pending_updates:
        store.label_advisory(prior_id, index, **fields)

    # 8. Render
    fix_steps = judge_output.fix_steps or compile_fix_steps(failures)
    if json_output:
        sys.stdout.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        sys.stdout.flush()
    elif render:
        con = console if console is not None else ux.get_console()
        if failures:
            # Nudge to `proofjury login` only when the block fell back to the
            # deterministic engine for lack of any configured LLM.
            suggest_login = (
                blocked
                and judge_output.model_id.startswith("deterministic/")
                and not llm_configured(env)
            )
            ux.render_blocked(
                con, record, failures, recalled, cmd, fix_steps,
                forced=force, suggest_login=suggest_login,
            )
        else:
            ux.render_allowed(con, record, results, cmd, no_exec)
        ux.render_advisories(con, record, agent_notes)

    # 9. Block or execute — the child is spawned ONLY when allowed.
    if blocked:
        exit_code = EXIT_BLOCKED
    elif no_exec or not cmd:
        exit_code = 0
    else:
        try:
            completed = subprocess.run(cmd, cwd=root, env=dict(env))
            rc = completed.returncode
        except FileNotFoundError:
            sys.stderr.write(f"proofjury: command not found: {cmd[0]}\n")
            rc = 127
        except PermissionError:
            sys.stderr.write(f"proofjury: command not executable: {cmd[0]}\n")
            rc = 126
        # A signal-killed child reports a negative returncode; use the
        # shell convention 128 + signal instead of wrapping modulo 256.
        exit_code = rc if rc >= 0 else 128 - rc

    return GateResult(
        record=record,
        results=results,
        failures=failures,
        blocked=blocked,
        exit_code=exit_code,
        recalled=recalled,
        agent_notes=agent_notes,
    )

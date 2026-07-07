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
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from . import __version__, ux
from .checks import CheckContext, CheckResult, run_checks
from .config import llm_configured
from .context import capture_context, git_summary, load_config
from .judge import DeterministicJudge, JudgeInput, JudgeOutput, get_judge
from .judge.deterministic import compile_fix_steps
from .memory.recall import recall, strong_match
from .memory.schema import MemoryRecord
from .memory.store import MemoryStore
from .session import load_session, now_iso, worktree_digest

EXIT_BLOCKED = 2
EXIT_INTERNAL_ERROR = 3

MIN_SCRUB_LENGTH = 8
REDACTED = "[REDACTED]"

# Env vars whose values are ambient context (paths, locale, terminal), not
# credentials. Scrubbing these would redact $HOME/$PWD out of every path in
# the proof record without protecting a secret. Name-based and conservative:
# anything not listed here is still scrubbed by value.
SAFE_ENV_NAMES = frozenset({
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


def run_gate(
    root: Path,
    action: str,
    cmd: list[str] | None,
    *,
    force: bool = False,
    no_exec: bool = False,
    json_output: bool = False,
    env: Mapping[str, str] | None = None,
    judge=None,
    render: bool = True,
    console=None,
) -> GateResult:
    started = time.monotonic()
    root = Path(root).resolve()
    env = dict(os.environ) if env is None else dict(env)

    proof_root = root / ".proofloop"
    proof_root.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(proof_root)
    record_id = store.next_id()

    # 1. Context / trace capture
    run_context = capture_context(root, env)
    config = load_config(root)
    digest = worktree_digest(root)
    session = load_session(root)

    # 2. Deterministic checks (never LLM)
    check_context = CheckContext(
        root=root,
        env=env,
        config=config,
        files=run_context.files,
        session=session,
        digest=digest,
    )
    results = run_checks(check_context)
    _scrub_results(results, env)
    failures = [r for r in results if not r.passed]

    # 3. Recall priors BEFORE judging, so the judge cites them
    priors = recall(store, run_context.repo_id, failures) if failures else []
    recalled = priors[0] if priors else None

    # 4. Judge (explanation only — pass/fail already decided above)
    summary = scrub_text(git_summary(run_context), env)
    judge_input = JudgeInput(
        action=action,
        repo_id=run_context.repo_id,
        failures=failures,
        git_summary=summary,
        priors=priors[:3],
    )
    if failures:
        if recalled is not None and strong_match(failures, recalled):
            # Known recurrence: cite the prior deterministically —
            # NO model call, even when an LLM judge is configured.
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
        "branch": scrub_text(run_context.branch, env) if run_context.branch else run_context.branch,
        "head_sha": run_context.head_sha,
        "dirty": run_context.dirty,
        "changed_files": [scrub_text(f, env) for f in run_context.changed_files],
        "agent_source": run_context.agent_source,
        "worktree_digest": digest,
        "env_fingerprint": run_context.env_fingerprint,  # names only, never values
        "cmd": [scrub_text(part, env) for part in cmd] if cmd else cmd,
        "action": action,
    }
    (run_dir / "checks.json").write_text(
        scrub_text(json.dumps(checks_payload, indent=2, ensure_ascii=False), env)
    )
    (run_dir / "context.json").write_text(
        scrub_text(json.dumps(context_payload, indent=2, ensure_ascii=False), env)
    )
    (run_dir / "diff.patch").write_text(scrub_text(run_context.diff_excerpt, env))

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
        context_ref=f".proofloop/runs/{record_id}/",
        checks=[
            {
                "name": r.name,
                "type": r.type,
                "passed": r.passed,
                "failure_class": r.failure_class,
                "evidence": scrub_text(r.evidence_str(), env),
            }
            for r in results
        ],
        gate_passed=gate_passed,
        diagnosis=scrub_text(judge_output.diagnosis, env),
        judge_input=scrub_text(judge_input.to_prompt_text(), env),
        judge_output=scrub_text(
            json.dumps(
                {"diagnosis": judge_output.diagnosis, "fix_steps": judge_output.fix_steps},
                ensure_ascii=False,
            ),
            env,
        ),
        proof_refs=["checks.json", "context.json", "diff.patch"],
        recalled_from=recalled.id if recalled is not None else None,
        judge_model_id=judge_output.model_id,
        resolution=resolution,
        schema_version="1",
        cli_version=__version__,
        gate_duration_ms=int((time.monotonic() - started) * 1000),
        inputs_hash=_inputs_hash(action, digest, run_context.files, root, run_context.env_fingerprint),
        env_fingerprint=run_context.env_fingerprint,
        resolves=resolves,
    )
    store.append(record)
    store.append_markdown(record)
    for prior in resolved_priors:
        store.update_resolution(
            prior.id,
            {"status": "auto_resolved", "resolved_by": record_id, "at": now_iso()},
        )

    # 8. Render
    fix_steps = judge_output.fix_steps or compile_fix_steps(failures)
    if json_output:
        sys.stdout.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        sys.stdout.flush()
    elif render:
        con = console if console is not None else ux.get_console()
        if failures:
            # Nudge to `proofloop login` only when the block fell back to the
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
            sys.stderr.write(f"proofloop: command not found: {cmd[0]}\n")
            rc = 127
        except PermissionError:
            sys.stderr.write(f"proofloop: command not executable: {cmd[0]}\n")
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
    )

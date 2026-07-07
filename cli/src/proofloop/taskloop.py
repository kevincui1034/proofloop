"""Task-loop judge for end-to-end agent benchmark runs.

This is deliberately separate from the deploy gate. The deploy gate blocks
production-affecting commands from deterministic repo checks; the task judge
audits an agent episode after (or during) a benchmark task and emits corrective
feedback when the agent refused local setup or substituted mock/stub behavior
for live UI/API verification.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .gate import EXIT_BLOCKED, scrub_text
from .session import now_iso
from .tasksetup import load_adapter

READ_LIMIT_BYTES = 2_000_000
MAX_VERIFY_TIMEOUT_SECONDS = 60 * 60
PENDING_FEEDBACK_FILE = "pending-task-feedback.json"

REFUSAL_PATTERNS = [
    re.compile(
        r"\b(?:i\s+)?(?:can't|cannot|could not|unable to|won't)\b"
        r".{0,140}\b(?:set\s*up|setup|install|local|locally|dependencies|"
        r"environment|run|execute)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:requires|needs|would need)\s+(?:a\s+)?local\s+"
        r"(?:setup|environment|machine|server)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:cannot|can't|unable to)\s+(?:access|run|start)\s+"
        r"(?:the\s+)?(?:local\s+)?(?:app|server|ui|browser)\b",
        re.IGNORECASE,
    ),
]

MOCK_PATTERNS = [
    re.compile(
        r"\b(?:mock(?:ed|ing)?|stub(?:bed|bing)?|fake|simulat(?:ed|ion|e)|"
        r"placeholder|hard-?coded|deterministic\s+demo\s+path|demo\s+path)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwithout\s+(?:hitting|calling|using|exercising)\s+(?:the\s+)?"
        r"(?:live\s+)?(?:api|backend|server|ui)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:not|never)\s+(?:actually\s+)?(?:wired|live|calling\s+the\s+api|"
        r"running\s+against\s+the\s+ui)\b",
        re.IGNORECASE,
    ),
]

LIVE_EVIDENCE_PATTERNS = [
    re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/(?:api|graphql|rpc)\b", re.IGNORECASE),
    re.compile(r"\bstatus(?:\s+code)?\s*[:=]?\s*2\d\d\b", re.IGNORECASE),
    re.compile(r"\bhttps?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|[^\s]+)\b", re.IGNORECASE),
    re.compile(r"\b(?:playwright|browser|screenshot|network|request|response|curl|fetch)\b", re.IGNORECASE),
]

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tgz", ".mp4", ".mov", ".avi", ".woff", ".woff2", ".ttf", ".otf",
}


@dataclass
class TranscriptText:
    all_text: str = ""
    assistant_text: str = ""
    trusted_text: str = ""


@dataclass
class TaskIssue:
    code: str
    severity: str
    evidence: str
    fix: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "evidence": self.evidence,
            "fix": self.fix,
        }


@dataclass
class TaskAssessment:
    id: str
    created_at: str
    task: str | None
    passed: bool
    issues: list[TaskIssue] = field(default_factory=list)
    transcript_path: str | None = None
    proof_paths: list[str] = field(default_factory=list)
    required_markers: list[str] = field(default_factory=list)
    verify_cmd: list[str] = field(default_factory=list)
    verify_exit_code: int | None = None
    verify_log: str | None = None
    agent_exit_code: int | None = None
    feedback_path: str | None = None
    assessment_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "task": self.task,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "transcript_path": self.transcript_path,
            "proof_paths": self.proof_paths,
            "required_markers": self.required_markers,
            "verify_cmd": self.verify_cmd,
            "verify_exit_code": self.verify_exit_code,
            "verify_log": self.verify_log,
            "agent_exit_code": self.agent_exit_code,
            "feedback_path": self.feedback_path,
            "assessment_path": self.assessment_path,
        }


@dataclass
class LoopResult:
    id: str
    passed: bool
    iterations: list[dict]
    run_dir: str
    changelog_path: str
    versions_path: str
    selected_task_path: str | None = None
    selected_task: dict | None = None
    final_assessment_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "passed": self.passed,
            "iterations": self.iterations,
            "run_dir": self.run_dir,
            "changelog_path": self.changelog_path,
            "versions_path": self.versions_path,
            "selected_task_path": self.selected_task_path,
            "selected_task": self.selected_task,
            "final_assessment_path": self.final_assessment_path,
        }


def _flatten_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_flatten_strings(item))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(_flatten_strings(item))
        return parts
    return []


def _entry_role(entry: dict) -> str | None:
    role = entry.get("role") or entry.get("type")
    message = entry.get("message")
    if isinstance(message, dict):
        role = message.get("role") or role
    return str(role).lower() if role else None


def read_transcript(path: Path | None) -> TranscriptText:
    if path is None:
        return TranscriptText()
    raw = _read_text_file(path)
    if not raw.strip():
        return TranscriptText()

    all_parts: list[str] = []
    assistant_parts: list[str] = []
    trusted_parts: list[str] = []
    parsed_any = False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        parsed_any = True
        text = "\n".join(_flatten_strings(entry)).strip()
        if text:
            all_parts.append(text)
        role = _entry_role(entry)
        if role in {"assistant", "agent", "model"} and text:
            assistant_parts.append(text)
        elif role not in {"user", "system"} and text:
            trusted_parts.append(text)

    if parsed_any:
        all_text = "\n".join(all_parts)
        assistant_text = "\n".join(assistant_parts) or all_text
        return TranscriptText(
            all_text=all_text,
            assistant_text=assistant_text,
            trusted_text="\n".join(trusted_parts),
        )
    return TranscriptText(all_text=raw, assistant_text=raw, trusted_text=raw)


def _read_text_file(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            data = fh.read(READ_LIMIT_BYTES)
        return data.decode("utf-8", errors="replace")
    except OSError as exc:
        return f"[proofloop could not read {path}: {exc}]"


def _read_proof_path(path: Path) -> str:
    if path.is_dir():
        parts: list[str] = []
        for child in sorted(path.rglob("*")):
            if not child.is_file() or child.suffix.lower() in BINARY_SUFFIXES:
                continue
            parts.append(f"\n--- {child} ---\n{_read_text_file(child)}")
        return "\n".join(parts)
    if path.suffix.lower() in BINARY_SUFFIXES:
        return f"[binary proof file supplied: {path}]"
    return _read_text_file(path)


def _first_match(patterns: list[re.Pattern], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(0).split())
    return None


def _has_live_evidence(text: str) -> bool:
    return any(pattern.search(text) for pattern in LIVE_EVIDENCE_PATTERNS)


def _next_task_id(root: Path) -> tuple[str, Path]:
    runs = root / ".proofloop" / "task-runs"
    runs.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        task_id = f"task_{index:03d}"
        path = runs / task_id
        try:
            path.mkdir()
            return task_id, path
        except FileExistsError:
            index += 1


def _run_verify(
    root: Path,
    cmd: list[str],
    timeout_seconds: int,
    env: Mapping[str, str],
) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=root,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        return completed.returncode, completed.stdout or ""
    except FileNotFoundError:
        return 127, f"proofloop: command not found: {cmd[0]}\n"
    except PermissionError:
        return 126, f"proofloop: command not executable: {cmd[0]}\n"
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return 124, output + f"\nproofloop: verify command timed out after {timeout_seconds}s\n"


def build_feedback(task: str | None, issues: list[TaskIssue]) -> str:
    lines = [
        "Proofloop task judge blocked this benchmark run.",
        "",
    ]
    if task:
        lines += ["Task under test:", task, ""]
    lines.append("Findings:")
    for issue in issues:
        lines.append(f"- {issue.code}: {issue.evidence}")
    lines += [
        "",
        "Corrective instruction for Codex:",
        "Continue the same task end to end. You have permission to set up the "
        "local project: install dependencies, create or reuse local env files, "
        "start the required dev servers, and run the benchmark against the live "
        "UI/backend. Do not stop because setup is local.",
        "",
        "Do not satisfy the task with mocks, stubs, hard-coded fixtures, or a "
        "deterministic demo path unless the task explicitly asks for a mock. "
        "Exercise the real UI/API path and collect evidence: command logs, "
        "server output, browser/network traces, screenshots when relevant, and "
        "the exact verification command result.",
        "",
        "After fixing the issue, rerun the live verification command and rerun "
        "Proofloop's task judge with the same transcript/proof markers.",
    ]
    return "\n".join(lines) + "\n"


def _stage_pending_feedback(
    root: Path, assessment: TaskAssessment, feedback: str, env: Mapping[str, str]
) -> None:
    pending = root / ".proofloop" / PENDING_FEEDBACK_FILE
    payload = {
        "task_id": assessment.id,
        "feedback_path": assessment.feedback_path,
        "feedback": feedback,
    }
    pending.write_text(
        scrub_text(json.dumps(payload, indent=2), env) + "\n",
        encoding="utf-8",
    )


def drain_pending_task_feedback(root: Path) -> list[str]:
    """Return staged task feedback once, then remove it.

    Hooks use this to deliver a task-judge block back to Codex/Claude as
    additional context on the next tool event. A malformed pending file is
    dropped rather than trapping the user in a repeated feedback loop.
    """
    pending = Path(root) / ".proofloop" / PENDING_FEEDBACK_FILE
    if not pending.is_file():
        return []
    try:
        data = json.loads(pending.read_text(encoding="utf-8"))
        pending.unlink(missing_ok=True)
    except Exception:
        try:
            pending.unlink(missing_ok=True)
        except Exception:
            pass
        return []
    feedback = data.get("feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        return []
    task_id = data.get("task_id") or "unknown"
    path = data.get("feedback_path")
    header = f"Proofloop task judge feedback from {task_id}"
    if isinstance(path, str) and path:
        header += f" ({path})"
    return [header + ":\n" + feedback.strip()]


def evaluate_task_run(
    root: Path,
    *,
    task: str | None,
    transcript_path: Path | None,
    proof_paths: list[Path] | None,
    verify_cmd: list[str] | None,
    required_markers: list[str] | None,
    require_live: bool,
    verify_timeout_seconds: int,
    env: Mapping[str, str],
    agent_exit_code: int | None = None,
) -> TaskAssessment:
    root = Path(root).resolve()
    task_id, run_dir = _next_task_id(root)
    proof_paths = list(proof_paths or [])
    required_markers = list(required_markers or [])
    verify_cmd = list(verify_cmd or [])
    verify_timeout_seconds = max(1, min(verify_timeout_seconds, MAX_VERIFY_TIMEOUT_SECONDS))

    transcript = read_transcript(transcript_path)
    proof_texts = [_read_proof_path(path) for path in proof_paths]
    verify_exit_code: int | None = None
    verify_output = ""
    verify_log_rel: str | None = None
    if verify_cmd:
        verify_exit_code, verify_output = _run_verify(
            root, verify_cmd, verify_timeout_seconds, env
        )
        verify_log = run_dir / "verify.log"
        verify_log.write_text(scrub_text(verify_output, env), encoding="utf-8")
        verify_log_rel = str(verify_log.relative_to(root))

    assistant_text = transcript.assistant_text
    evidence_text = "\n".join(
        part for part in [transcript.all_text, *proof_texts, verify_output] if part
    )
    trusted_evidence_text = "\n".join(
        part for part in [transcript.trusted_text, *proof_texts, verify_output] if part
    )

    issues: list[TaskIssue] = []
    refusal = _first_match(REFUSAL_PATTERNS, assistant_text)
    if refusal:
        issues.append(
            TaskIssue(
                code="local_setup_refusal",
                severity="block",
                evidence=refusal,
                fix=(
                    "Tell the agent to perform the local setup itself, install "
                    "dependencies, start services, and rerun the task."
                ),
            )
        )

    mock = _first_match(MOCK_PATTERNS, assistant_text)
    if mock:
        issues.append(
            TaskIssue(
                code="mock_or_stub_completion",
                severity="block",
                evidence=mock,
                fix=(
                    "Require live UI/backend execution and prohibit mocks, stubs, "
                    "hard-coded fixtures, or deterministic demo paths unless "
                    "explicitly requested."
                ),
            )
        )

    if verify_cmd and verify_exit_code not in (0, None):
        issues.append(
            TaskIssue(
                code="verification_failed",
                severity="block",
                evidence=f"verify command exited {verify_exit_code}: {' '.join(verify_cmd)}",
                fix="Fix the app/task until the live verification command exits 0.",
            )
        )

    if agent_exit_code not in (None, 0):
        issues.append(
            TaskIssue(
                code="agent_execution_failed",
                severity="block",
                evidence=f"codex command exited {agent_exit_code}",
                fix=(
                    "Fix the Codex execution/setup failure, rerun the agent, "
                    "and judge the resulting live task trace."
                ),
            )
        )

    marker_text = trusted_evidence_text if require_live else evidence_text
    lower_evidence = marker_text.lower()
    for marker in required_markers:
        if marker.lower() not in lower_evidence:
            issues.append(
                TaskIssue(
                    code="required_live_marker_missing",
                    severity="block",
                    evidence=f"missing marker: {marker}",
                    fix=(
                        "Rerun against the live UI/API path and attach proof "
                        f"showing marker {marker!r}."
                    ),
                )
            )

    if require_live and not verify_cmd and not proof_paths:
        issues.append(
            TaskIssue(
                code="missing_live_evidence",
                severity="block",
                evidence="no verifier command or proof artifact was provided",
                fix=(
                    "Provide a verification command, proof log, browser/network "
                    "trace, or server output from the live UI/API path."
                ),
            )
        )
    elif require_live and not _has_live_evidence(trusted_evidence_text):
        issues.append(
            TaskIssue(
                code="missing_live_evidence",
                severity="block",
                evidence="no trusted verifier/proof live UI/API evidence was provided",
                fix=(
                    "Provide verifier output or proof logs showing a real "
                    "browser/API/server interaction, not just an assistant claim."
                ),
            )
        )

    passed = not any(issue.severity == "block" for issue in issues)
    assessment = TaskAssessment(
        id=task_id,
        created_at=now_iso(),
        task=scrub_text(task or "", env) or None,
        passed=passed,
        issues=[
            TaskIssue(
                issue.code,
                issue.severity,
                scrub_text(issue.evidence, env),
                scrub_text(issue.fix, env),
            )
            for issue in issues
        ],
        transcript_path=str(transcript_path) if transcript_path else None,
        proof_paths=[str(path) for path in proof_paths],
        required_markers=required_markers,
        verify_cmd=[scrub_text(part, env) for part in verify_cmd],
        verify_exit_code=verify_exit_code,
        verify_log=verify_log_rel,
        agent_exit_code=agent_exit_code,
    )

    if assessment.issues:
        feedback = build_feedback(assessment.task, assessment.issues)
        feedback_path = run_dir / "feedback.md"
        feedback_path.write_text(scrub_text(feedback, env), encoding="utf-8")
        assessment.feedback_path = str(feedback_path.relative_to(root))
        _stage_pending_feedback(root, assessment, feedback, env)

    assessment_path = run_dir / "assessment.json"
    assessment.assessment_path = str(assessment_path.relative_to(root))
    assessment_path.write_text(
        scrub_text(json.dumps(assessment.to_dict(), indent=2), env) + "\n",
        encoding="utf-8",
    )
    return assessment


def task_exit_code(assessment: TaskAssessment) -> int:
    return 0 if assessment.passed else EXIT_BLOCKED


def run_codex_task_loop(
    root: Path,
    *,
    task: str,
    benchmark: str,
    adapter_path: Path | None,
    verify_cmd: list[str],
    required_markers: list[str],
    codex_cmd: str | None,
    max_iterations: int,
    env: Mapping[str, str],
    selected_task: dict | None = None,
) -> LoopResult:
    root = Path(root).resolve()
    loop_id, loop_dir = _next_loop_id(root)
    adapter = load_adapter(adapter_path) if adapter_path else {}
    if not required_markers:
        required_markers = [
            str(marker)
            for marker in adapter.get("required_live_markers", [])
            if isinstance(marker, str)
        ]
    max_iterations = max(1, max_iterations)
    iterations: list[dict] = []
    feedback = ""
    passed = False
    final_assessment_path: str | None = None
    changelog_path = loop_dir / "changelog.md"
    versions_path = loop_dir / "versions.jsonl"
    selected_task_path: str | None = None
    if selected_task:
        selected_path = loop_dir / "selected-task.json"
        selected_path.write_text(
            scrub_text(json.dumps(selected_task, indent=2, ensure_ascii=False), env)
            + "\n",
            encoding="utf-8",
        )
        selected_task_path = str(selected_path.relative_to(root))
    baseline_changed_files = _git_changed_files(root)

    for index in range(1, max_iterations + 1):
        before_changed_files = _git_changed_files(root)
        prompt = _loop_prompt(
            task=task,
            benchmark=benchmark,
            adapter=adapter,
            previous_feedback=feedback,
            iteration=index,
            max_iterations=max_iterations,
            selected_task=selected_task,
        )
        prompt_path = loop_dir / f"iteration-{index:02d}-prompt.md"
        prompt_path.write_text(scrub_text(prompt, env), encoding="utf-8")

        trace_path = loop_dir / f"iteration-{index:02d}-codex.jsonl"
        codex_log_path = loop_dir / f"iteration-{index:02d}-codex.stderr.log"
        codex_exit = _run_codex_exec(codex_cmd, prompt, root, trace_path, codex_log_path, env)

        proof_paths = [codex_log_path]
        assessment = evaluate_task_run(
            root,
            task=task,
            transcript_path=trace_path,
            proof_paths=proof_paths,
            verify_cmd=verify_cmd,
            required_markers=required_markers,
            require_live=True,
            verify_timeout_seconds=600,
            env=env,
            agent_exit_code=codex_exit,
        )
        after_changed_files = _git_changed_files(root)
        final_assessment_path = assessment.assessment_path
        row = {
            "iteration": index,
            "created_at": now_iso(),
            "git_head": _git_head(root),
            "codex_exit_code": codex_exit,
            "prompt": str(prompt_path.relative_to(root)),
            "transcript": str(trace_path.relative_to(root)),
            "codex_log": str(codex_log_path.relative_to(root)),
            "assessment": assessment.assessment_path,
            "selected_task": selected_task_path,
            "verify_log": assessment.verify_log,
            "feedback": assessment.feedback_path,
            "passed": assessment.passed,
            "issues": [issue.to_dict() for issue in assessment.issues],
            "changed_files_before": before_changed_files,
            "changed_files_after": after_changed_files,
            "changed_files_since_loop_start": [
                item for item in after_changed_files if item not in baseline_changed_files
            ],
        }
        iterations.append(row)
        with versions_path.open("a", encoding="utf-8") as fh:
            fh.write(scrub_text(json.dumps(row, ensure_ascii=False), env) + "\n")
        _write_loop_changelog(
            changelog_path,
            loop_id,
            task,
            benchmark,
            iterations,
            env,
            selected_task_path=selected_task_path,
        )
        if assessment.passed:
            passed = True
            break
        feedback = ""
        if assessment.feedback_path:
            try:
                feedback = (root / assessment.feedback_path).read_text(encoding="utf-8")
            except OSError:
                feedback = build_feedback(assessment.task, assessment.issues)

    result = LoopResult(
        id=loop_id,
        passed=passed,
        iterations=iterations,
        run_dir=str(loop_dir.relative_to(root)),
        changelog_path=str(changelog_path.relative_to(root)),
        versions_path=str(versions_path.relative_to(root)),
        selected_task_path=selected_task_path,
        selected_task=selected_task,
        final_assessment_path=final_assessment_path,
    )
    (loop_dir / "loop.json").write_text(
        scrub_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), env) + "\n",
        encoding="utf-8",
    )
    return result


def loop_exit_code(result: LoopResult) -> int:
    return 0 if result.passed else EXIT_BLOCKED


def _next_loop_id(root: Path) -> tuple[str, Path]:
    runs = root / ".proofloop" / "task-runs"
    runs.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        loop_id = f"loop_{index:03d}"
        path = runs / loop_id
        try:
            path.mkdir()
            return loop_id, path
        except FileExistsError:
            index += 1


def _run_codex_exec(
    codex_cmd: str | None,
    prompt: str,
    root: Path,
    trace_path: Path,
    stderr_path: Path,
    env: Mapping[str, str],
) -> int:
    command = shlex.split(codex_cmd or "codex exec --json")
    if not command:
        command = ["codex", "exec", "--json"]
    command.append(prompt)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        trace_path.write_text(scrub_text(completed.stdout or "", env), encoding="utf-8")
        stderr_path.write_text(scrub_text(completed.stderr or "", env), encoding="utf-8")
        return completed.returncode
    except FileNotFoundError:
        trace_path.write_text("", encoding="utf-8")
        stderr_path.write_text(
            f"proofloop: codex command not found: {command[0]}\n", encoding="utf-8"
        )
        return 127
    except PermissionError:
        trace_path.write_text("", encoding="utf-8")
        stderr_path.write_text(
            f"proofloop: codex command not executable: {command[0]}\n", encoding="utf-8"
        )
        return 126


def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _git_changed_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    files: list[str] = []
    for entry in completed.stdout.split("\0"):
        if not entry:
            continue
        path = entry[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        normalized = path.replace("\\", "/")
        if normalized.startswith(".proofloop/task-runs/"):
            continue
        if normalized == ".proofloop/pending-task-feedback.json":
            continue
        files.append(normalized)
    return sorted(dict.fromkeys(files))


def _loop_prompt(
    *,
    task: str,
    benchmark: str,
    adapter: dict,
    previous_feedback: str,
    iteration: int,
    max_iterations: int,
    selected_task: dict | None = None,
) -> str:
    setup_commands = adapter.get("setup_commands") or []
    run_commands = adapter.get("run_commands") or []
    verify_commands = adapter.get("verify_commands") or []
    markers = adapter.get("required_live_markers") or []
    meta_rubric = adapter.get("meta_rubric")
    lines = [
        f"You are running a Proofloop benchmark task loop ({iteration}/{max_iterations}).",
        f"Benchmark: {benchmark}",
        "",
        "Task:",
        task,
        "",
        "Required behavior:",
        "- Search the repo and set up the local environment if anything is missing.",
        "- Install dependencies, create local-only env files if needed, and start real services.",
        "- Run the task end to end through the live UI/API path.",
        "- Do not use mocks, stubs, hard-coded fixtures, or deterministic demo paths unless the task explicitly asks for them.",
        "- Preserve a clear changelog of files changed, commands run, and evidence collected.",
        "- Finish with the exact proof artifact paths and live markers observed.",
    ]
    if setup_commands:
        lines += ["", "Adapter setup command candidates:", json.dumps(setup_commands)]
    if run_commands:
        lines += ["", "Adapter run command candidates:", json.dumps(run_commands)]
    if verify_commands:
        lines += ["", "Adapter verify command candidates:", json.dumps(verify_commands)]
    if markers:
        lines += ["", "Required live markers:", json.dumps(markers)]
    if selected_task:
        lines += [
            "",
            "Proofloop-selected benchmark task:",
            json.dumps(selected_task, ensure_ascii=False),
        ]
    if isinstance(meta_rubric, dict) and meta_rubric:
        lines += [
            "",
            "Live browser benchmark meta-rubric:",
            json.dumps(meta_rubric, ensure_ascii=False),
        ]
    if previous_feedback:
        lines += ["", "Previous Proofloop judge feedback to fix:", previous_feedback.strip()]
    return "\n".join(lines) + "\n"


def _write_loop_changelog(
    path: Path,
    loop_id: str,
    task: str,
    benchmark: str,
    iterations: list[dict],
    env: Mapping[str, str],
    selected_task_path: str | None = None,
) -> None:
    lines = [
        f"# Proofloop task loop {loop_id}",
        "",
        f"- benchmark: {benchmark}",
        f"- task: {task}",
        f"- updated_at: {now_iso()}",
    ]
    if selected_task_path:
        lines.append(f"- selected_task: {selected_task_path}")
    lines += ["", "## Iterations"]
    for row in iterations:
        lines += [
            "",
            f"### Iteration {row['iteration']}",
            f"- git_head: {row.get('git_head')}",
            f"- codex_exit_code: {row['codex_exit_code']}",
            f"- passed: {row['passed']}",
            f"- prompt: {row['prompt']}",
            f"- transcript: {row['transcript']}",
            f"- assessment: {row['assessment']}",
        ]
        if row.get("selected_task"):
            lines.append(f"- selected_task: {row['selected_task']}")
        if row.get("verify_log"):
            lines.append(f"- verify_log: {row['verify_log']}")
        if row.get("feedback"):
            lines.append(f"- feedback: {row['feedback']}")
        changed_files = row.get("changed_files_since_loop_start") or []
        if changed_files:
            lines.append("- changed_files_since_loop_start:")
            lines += [f"  - {item}" for item in changed_files]
        for issue in row["issues"]:
            lines.append(f"- issue: {issue['code']} - {issue['evidence']}")
    path.write_text(scrub_text("\n".join(lines) + "\n", env), encoding="utf-8")

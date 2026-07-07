"""Task-run memory bridge for benchmark outcomes.

This module is intentionally separate from ``proofloop.memory``. Gate memory
records are the deploy/advisory authority path; task-run rows are an additive
dataset layer over ``.proofloop/task-runs`` artifacts.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

TASK_RUN_MEMORY_SCHEMA_VERSION = "task-run-memory-v1"
TASK_RUN_MEMORY_FILE = "task-run-memory.jsonl"
TASK_RUNS_DIR = "task-runs"
TASK_PASSED_LABEL = "task_passed"
TASK_BLOCKED_LABEL = "task_blocked"

_ITERATION_PATH_KEYS = ("prompt", "transcript", "codex_log", "assessment", "selected_task")


def task_run_label(passed: object) -> str:
    return TASK_PASSED_LABEL if bool(passed) else TASK_BLOCKED_LABEL


def iter_task_run_records(
    root: Path,
    *,
    include_loops: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield training-ready JSON rows from ``.proofloop/task-runs``.

    ``root`` may be either the repo root or the ``.proofloop`` directory. The
    rows only reference artifact paths; transcript/proof contents are not read
    or inlined, so scrubbed references from ``assessment.json`` are preserved.
    """

    repo_root, proof_root = _resolve_roots(root)
    task_runs = proof_root / TASK_RUNS_DIR
    if not task_runs.is_dir():
        return

    loop_contexts = _loop_contexts(repo_root, task_runs) if include_loops else {}
    for assessment_path in sorted(task_runs.glob("task_*/assessment.json")):
        record = _assessment_record(repo_root, assessment_path, loop_contexts)
        if record is not None:
            yield record

    if include_loops:
        for loop_path in sorted(task_runs.glob("loop_*/loop.json")):
            record = _loop_record(repo_root, loop_path)
            if record is not None:
                yield record


def write_task_run_memory(
    root: Path,
    output: Path | None = None,
    *,
    include_loops: bool = True,
) -> int:
    """Write task-run memory rows to JSONL and return the row count.

    The default output is ``.proofloop/task-run-memory.jsonl``. The file is
    replaced atomically and is deliberately separate from gate memory.
    """

    repo_root, proof_root = _resolve_roots(root)
    output_path = Path(output) if output is not None else proof_root / TASK_RUN_MEMORY_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(iter_task_run_records(repo_root, include_loops=include_loops))
    fd, tmp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp_name, output_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return len(rows)


def _resolve_roots(root: Path) -> tuple[Path, Path]:
    path = Path(root).resolve()
    if path.name == ".proofloop":
        return path.parent, path
    return path, path / ".proofloop"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_ref(root: Path, ref: object) -> str | None:
    if not isinstance(ref, str):
        return None
    text = ref.strip()
    if not text:
        return None

    path = Path(text)
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return text.replace("\\", "/")


def _path_ref(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def _ref_to_path(root: Path, ref: str | None) -> Path | None:
    if ref is None:
        return None
    path = Path(ref)
    return path if path.is_absolute() else root / path


def _dedupe(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalized_path_list(root: Path, value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        normalized = _normalize_ref(root, item)
        if normalized is not None:
            refs.append(normalized)
    return refs


def _assessment_record(
    root: Path,
    assessment_path: Path,
    loop_contexts: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    data = _read_json(assessment_path)
    if data is None:
        return None

    assessment_ref = _normalize_ref(root, data.get("assessment_path")) or _path_ref(
        root, assessment_path
    )
    transcript_ref = _normalize_ref(root, data.get("transcript_path"))
    proof_refs = _normalized_path_list(root, data.get("proof_paths"))
    verify_log = _normalize_ref(root, data.get("verify_log"))
    feedback_path = _normalize_ref(root, data.get("feedback_path"))
    passed = bool(data.get("passed"))

    record: dict[str, Any] = {
        "schema_version": TASK_RUN_MEMORY_SCHEMA_VERSION,
        "id": str(data.get("id") or assessment_path.parent.name),
        "source": "task_run",
        "created_at": str(data.get("created_at") or ""),
        "label": task_run_label(passed),
        "passed": passed,
        "task": data.get("task"),
        "assessment_path": assessment_ref,
        "trace_ref": transcript_ref,
        "transcript_path": transcript_ref,
        "proof_refs": proof_refs,
        "proof_paths": proof_refs,
        "evidence_paths": _dedupe(
            [assessment_ref, transcript_ref, *proof_refs, verify_log, feedback_path]
        ),
        "issues": data.get("issues") if isinstance(data.get("issues"), list) else [],
        "required_markers": (
            data.get("required_markers")
            if isinstance(data.get("required_markers"), list)
            else []
        ),
        "verify_cmd": data.get("verify_cmd") if isinstance(data.get("verify_cmd"), list) else [],
        "verify_exit_code": data.get("verify_exit_code"),
        "verify_log": verify_log,
        "feedback_path": feedback_path,
    }

    loop_context = loop_contexts.get(assessment_ref)
    if loop_context is not None:
        record.update(loop_context)
        record["evidence_paths"] = _dedupe(
            [*record["evidence_paths"], *loop_context.get("loop_artifact_paths", [])]
        )
    return record


def _loop_contexts(root: Path, task_runs: Path) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for loop_path in sorted(task_runs.glob("loop_*/loop.json")):
        data = _read_json(loop_path)
        if data is None:
            continue
        loop_ref = _path_ref(root, loop_path)
        changelog_ref = _normalize_ref(root, data.get("changelog_path"))
        versions_ref = _normalize_ref(root, data.get("versions_path"))
        loop_base_artifacts = _dedupe([loop_ref, changelog_ref, versions_ref])

        iterations = data.get("iterations")
        if not isinstance(iterations, list):
            continue
        for row in iterations:
            if not isinstance(row, dict):
                continue
            assessment_ref = _normalize_ref(root, row.get("assessment"))
            if assessment_ref is None:
                continue
            iteration_artifacts = _iteration_artifact_paths(root, row)
            contexts[assessment_ref] = {
                "loop_id": str(data.get("id") or loop_path.parent.name),
                "loop_iteration": row.get("iteration"),
                "loop_path": loop_ref,
                "loop_changelog_path": changelog_ref,
                "loop_versions_path": versions_ref,
                "loop_artifact_paths": _dedupe(
                    [*loop_base_artifacts, *iteration_artifacts]
                ),
            }
    return contexts


def _loop_record(root: Path, loop_path: Path) -> dict[str, Any] | None:
    data = _read_json(loop_path)
    if data is None:
        return None

    loop_ref = _path_ref(root, loop_path)
    run_dir = _normalize_ref(root, data.get("run_dir")) or _path_ref(root, loop_path.parent)
    changelog_ref = _normalize_ref(root, data.get("changelog_path"))
    versions_ref = _normalize_ref(root, data.get("versions_path"))
    final_assessment_ref = _normalize_ref(root, data.get("final_assessment_path"))
    passed = bool(data.get("passed"))

    iterations: list[dict[str, Any]] = []
    evidence_paths = _dedupe([loop_ref, changelog_ref, versions_ref, final_assessment_ref])
    trace_refs: list[str | None] = []
    proof_refs: list[str | None] = []
    created_at = ""

    raw_iterations = data.get("iterations")
    if isinstance(raw_iterations, list):
        for row in raw_iterations:
            if not isinstance(row, dict):
                continue
            normalized = dict(row)
            for key in _ITERATION_PATH_KEYS:
                if key in normalized:
                    normalized[key] = _normalize_ref(root, normalized[key])
            if not created_at:
                created_at = str(row.get("created_at") or "")
            trace_refs.append(normalized.get("transcript"))
            proof_refs.append(normalized.get("codex_log"))
            evidence_paths = _dedupe([*evidence_paths, *_iteration_artifact_paths(root, row)])
            iterations.append(normalized)

    final_assessment = _read_json(_ref_to_path(root, final_assessment_ref) or Path())
    if final_assessment is not None:
        if not created_at:
            created_at = str(final_assessment.get("created_at") or "")
        trace_refs.append(_normalize_ref(root, final_assessment.get("transcript_path")))
        proof_refs.extend(_normalized_path_list(root, final_assessment.get("proof_paths")))
        evidence_paths = _dedupe(
            [
                *evidence_paths,
                _normalize_ref(root, final_assessment.get("verify_log")),
                _normalize_ref(root, final_assessment.get("feedback_path")),
            ]
        )

    return {
        "schema_version": TASK_RUN_MEMORY_SCHEMA_VERSION,
        "id": str(data.get("id") or loop_path.parent.name),
        "source": "task_loop",
        "created_at": created_at,
        "label": task_run_label(passed),
        "passed": passed,
        "task": final_assessment.get("task") if final_assessment else None,
        "loop_path": loop_ref,
        "run_dir": run_dir,
        "changelog_path": changelog_ref,
        "versions_path": versions_ref,
        "assessment_path": final_assessment_ref,
        "final_assessment_path": final_assessment_ref,
        "trace_ref": next((ref for ref in trace_refs if ref), None),
        "proof_refs": _dedupe(proof_refs),
        "evidence_paths": evidence_paths,
        "iterations": iterations,
    }


def _iteration_artifact_paths(root: Path, row: dict[str, Any]) -> list[str]:
    refs: list[str | None] = []
    for key in _ITERATION_PATH_KEYS:
        refs.append(_normalize_ref(root, row.get(key)))
    return _dedupe(refs)

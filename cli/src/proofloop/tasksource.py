"""Benchmark task source loading and selection."""

from __future__ import annotations

import json
import os
import random
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .session import now_iso

DEFAULT_BANKERTOOLBENCH_SOURCE = "huggingface:Handshake-AI-Research/bankertoolbench"
STATE_DIR = "benchmark-state"
TASK_ID_FIELDS = ("task_id", "id", "uuid", "name")
PROMPT_FIELDS = ("final_prompt", "prompt", "task", "instruction", "user_prompt")
INPUT_REF_FIELDS = ("input_refs", "input_files", "inputs", "task_data")


class TaskSourceError(RuntimeError):
    """Raised when Proofloop cannot load or select a benchmark task."""


def select_benchmark_task(
    root: Path,
    benchmark: str,
    source: str | None,
    pick: str,
    task_id: str | None = None,
    filters: dict[str, str] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Load a task source and return one JSON-serializable selected task."""
    root = Path(root).resolve()
    resolved_source = source or _default_source_for_benchmark(benchmark)
    tasks, source_meta = load_task_source(root, resolved_source)
    filter_values = _normalize_filters(filters)
    filtered = _filter_tasks(tasks, filter_values)
    if not filtered:
        raise TaskSourceError(
            f"task source loaded, but no tasks matched filters {filter_values!r}"
        )

    chosen, selection = _pick_task(
        root=root,
        benchmark=benchmark,
        tasks=filtered,
        pick=pick,
        task_id=task_id,
        seed=seed,
        source_meta=source_meta,
        filters=filter_values,
    )
    selection["count"] = len(filtered)
    selection["filters"] = filter_values
    normalized = _normalize_task(root, chosen, source_meta, selection)
    if selection["mode"] == "next":
        _write_state(root, benchmark, normalized, selection, source_meta, filter_values)
    return normalized


def load_task_source(root: Path, source: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return raw task rows and source metadata for local or Hugging Face sources."""
    source = (source or "").strip()
    if not source:
        raise TaskSourceError("missing task source")
    source_lower = source.lower()
    if source_lower.startswith(("hf:", "huggingface:")):
        return _load_huggingface_source(source)
    if source_lower.startswith(("http://", "https://")):
        text = _read_url(source)
        return _parse_task_text(
            text,
            {
                "type": "url",
                "kind": "url",
                "source": source,
                "identity": f"url:{source}",
            },
            file_format=_format_from_path(source),
        )

    path = Path(source)
    if not path.is_absolute():
        path = root / path
    return _load_local_source(path)


def _default_source_for_benchmark(benchmark: str) -> str:
    if benchmark.lower().replace("_", "-") in {"bankertoolbench", "banker-toolbench"}:
        return DEFAULT_BANKERTOOLBENCH_SOURCE
    raise TaskSourceError(
        "no default task source for benchmark; pass --task-source or --task"
    )


def _load_huggingface_source(source: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repo = source.split(":", 1)[1].strip()
    if not repo:
        repo = "Handshake-AI-Research/bankertoolbench"
    revision = "main"
    if "@" in repo:
        repo, revision = repo.rsplit("@", 1)
        repo = repo.strip()
        revision = revision.strip() or "main"
    quoted_repo = urllib.parse.quote(repo, safe="/")
    quoted_revision = urllib.parse.quote(revision, safe="")
    base = f"https://huggingface.co/datasets/{quoted_repo}/resolve/{quoted_revision}"
    errors: list[str] = []
    for filename in ("tasks.jsonl", "tasks.json"):
        url = f"{base}/{filename}"
        try:
            text = _read_url(url)
        except TaskSourceError as exc:
            errors.append(str(exc))
            continue
        return _parse_task_text(
            text,
            {
                "type": "huggingface",
                "kind": "huggingface",
                "source": source,
                "repo": repo,
                "repo_id": repo,
                "revision": revision,
                "url": url,
                "path": filename,
                "identity": f"huggingface:{repo}@{revision}/{filename}",
            },
            file_format=_format_from_path(filename),
        )
    raise TaskSourceError("could not load Hugging Face task source: " + "; ".join(errors))


def _load_local_source(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path.is_dir():
        for filename in ("tasks.jsonl", "tasks.json"):
            candidate = path / filename
            if candidate.is_file():
                tasks, meta = _parse_task_text(
                    candidate.read_text(encoding="utf-8"),
                    {
                        "type": "local",
                        "kind": "local",
                        "source": str(path),
                        "path": str(candidate),
                        "root": str(path),
                        "format": _format_from_path(candidate.name),
                        "identity": f"local:{candidate.resolve()}",
                    },
                    file_format=_format_from_path(candidate.name),
                )
                return tasks, meta
        raise TaskSourceError(f"no tasks.jsonl or tasks.json found under {path}")
    if not path.is_file():
        raise TaskSourceError(f"task source not found: {path}")
    return _parse_task_text(
        path.read_text(encoding="utf-8"),
        {
            "type": "local",
            "kind": "local",
            "source": str(path),
            "path": str(path),
            "root": str(path.parent),
            "format": _format_from_path(path.name),
            "identity": f"local:{path.resolve()}",
        },
        file_format=_format_from_path(path.name),
    )


def _parse_task_text(
    text: str,
    source_meta: dict[str, Any],
    *,
    file_format: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stripped = text.lstrip()
    if not stripped:
        raise TaskSourceError("task source was empty")
    if file_format == "jsonl":
        tasks = _parse_jsonl(text)
    elif file_format == "json":
        tasks = _parse_json_rows(text)
    elif stripped.startswith("["):
        tasks = _parse_json_rows(text)
    elif "\n" in stripped:
        tasks = _parse_jsonl(text)
    elif stripped.startswith("{"):
        tasks = _parse_json_rows(text)
    else:
        tasks = _parse_jsonl(text)
    if not tasks:
        raise TaskSourceError("task source contained no object rows")
    meta = dict(source_meta)
    meta["count"] = len(tasks)
    if file_format:
        meta["format"] = file_format
    return tasks, meta


def _format_from_path(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".json":
        return "json"
    return None


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TaskSourceError(f"invalid JSONL at line {line_no}: {exc}") from exc
        tasks.append(_coerce_task_row(row, None, f"line {line_no}"))
    return tasks


def _parse_json_rows(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskSourceError(f"invalid JSON task source: {exc}") from exc

    if isinstance(data, list):
        return [
            _coerce_task_row(row, None, f"index {index}")
            for index, row in enumerate(data)
        ]
    if not isinstance(data, dict):
        raise TaskSourceError("JSON task source must be an object or list")

    for key in ("tasks", "data", "rows", "examples"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [
                _coerce_task_row(row, None, f"{key}[{index}]")
                for index, row in enumerate(rows)
            ]

    if _looks_like_task(data):
        return [_coerce_task_row(data, None, "object")]

    tasks: list[dict[str, Any]] = []
    for key, row in data.items():
        if isinstance(row, dict):
            tasks.append(_coerce_task_row(row, str(key), str(key)))
    if tasks:
        return tasks
    raise TaskSourceError("JSON task source must be a list or contain tasks[]")


def _coerce_task_row(value: Any, id_hint: str | None, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskSourceError(f"task source row at {label} must be an object")
    row = dict(value)
    if id_hint and not any(row.get(key) for key in TASK_ID_FIELDS):
        row["task_id"] = id_hint
    return row


def _looks_like_task(row: dict[str, Any]) -> bool:
    return any(key in row for key in (*TASK_ID_FIELDS, *PROMPT_FIELDS))


def _read_url(url: str) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "proofloop/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TaskSourceError(f"could not read {url}: {exc}") from exc


def _filter_tasks(tasks: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    if not filters:
        return tasks
    out: list[dict[str, Any]] = []
    for row in tasks:
        keep = True
        for key, expected in filters.items():
            actual = _field_value(row, key)
            if not _filter_value_matches(actual, expected):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def _field_value(row: dict[str, Any], key: str) -> Any:
    current: Any = row
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _filter_value_matches(actual: Any, expected: str) -> bool:
    if actual is None:
        return False
    if isinstance(actual, list):
        return any(_filter_value_matches(item, expected) for item in actual)
    return str(actual).lower() == str(expected).lower()


def _normalize_filters(filters: dict[str, str] | None) -> dict[str, str]:
    if not filters:
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in filters.items()
        if str(key).strip()
    }


def _pick_task(
    *,
    root: Path,
    benchmark: str,
    tasks: list[dict[str, Any]],
    pick: str,
    task_id: str | None,
    seed: int | None,
    source_meta: dict[str, Any] | None = None,
    filters: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mode = (pick or "next").strip()
    explicit_id = task_id or (mode if mode not in {"next", "random"} else None)
    if explicit_id:
        for index, row in enumerate(tasks):
            if _task_id(row, index) == explicit_id:
                return row, {"mode": "task_id", "task_id": explicit_id, "index": index}
        raise TaskSourceError(f"task id not found: {explicit_id}")

    if mode == "random":
        rng = random.Random(seed)
        index = rng.randrange(len(tasks))
        return tasks[index], {"mode": "random", "seed": seed, "index": index}
    if mode != "next":
        raise TaskSourceError("--pick-task must be next, random, or a task id")

    state = _read_state(root, benchmark)
    next_index = int(state.get("next_index", 0)) if isinstance(state, dict) else 0
    index = next_index % len(tasks)
    return tasks[index], {"mode": "next", "index": index, "next_index": index + 1}


def _normalize_task(
    root: Path,
    row: dict[str, Any],
    source_meta: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    index = int(selection.get("index", 0))
    task_id = _task_id(row, index)
    prompt = _prompt(row)
    if not prompt:
        raise TaskSourceError(f"selected task {task_id} has no prompt text")
    return {
        "task_id": task_id,
        "task": prompt,
        "source": source_meta,
        "selection": selection,
        "input_refs": _input_refs(root, task_id, row, source_meta),
        "metadata": _metadata(row),
        "raw": row,
    }


def _task_id(row: dict[str, Any], index: int) -> str:
    for key in ("task_id", "id", "uuid", "name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"task-{index + 1:03d}"


def _prompt(row: dict[str, Any]) -> str:
    for key in ("final_prompt", "prompt", "task", "instruction", "user_prompt"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    prompt_keys = {"final_prompt", "prompt", "task", "instruction", "user_prompt"}
    skip = prompt_keys | {"prompt_context", "formatting_context"}
    return {
        key: value
        for key, value in row.items()
        if key not in skip and isinstance(value, (str, int, float, bool, type(None)))
    }


def _input_refs(
    root: Path,
    task_id: str,
    row: dict[str, Any],
    source_meta: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    for key in ("input_refs", "input_files", "inputs", "task_data"):
        refs.extend(_flatten_refs(row.get(key)))
    source_root = source_meta.get("root")
    if isinstance(source_root, str):
        candidate = Path(source_root) / "task-data" / task_id / "Inputs"
        if candidate.is_dir():
            for child in sorted(candidate.rglob("*")):
                if child.is_file():
                    refs.append(_rel_or_text(root, child))
    elif source_meta.get("type") == "huggingface":
        refs.append(f"task-data/{task_id}/Inputs")
    return _dedupe(refs)


def _flatten_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        refs: list[str] = []
        for item in value.values():
            refs.extend(_flatten_refs(item))
        return refs
    if isinstance(value, list):
        refs = []
        for item in value:
            refs.extend(_flatten_refs(item))
        return refs
    return []


def _rel_or_text(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def _state_path(root: Path, benchmark: str) -> Path:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in benchmark).strip("-")
    safe = safe or "benchmark"
    return root / ".proofloop" / STATE_DIR / f"{safe}.json"


def _read_state(root: Path, benchmark: str) -> dict[str, Any]:
    path = _state_path(root, benchmark)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(
    root: Path,
    benchmark: str,
    selected: dict[str, Any],
    selection: dict[str, Any],
    source_meta: dict[str, Any] | None = None,
    filters: dict[str, str] | None = None,
) -> None:
    path = _state_path(root, benchmark)
    path.parent.mkdir(parents=True, exist_ok=True)
    next_index = int(selection.get("next_index", int(selection.get("index", 0)) + 1))
    payload = {
        "updated_at": now_iso(),
        "benchmark": benchmark,
        "last_task_id": selected["task_id"],
        "last_selection": selection,
        "source": source_meta,
        "filters": filters or {},
        "next_index": next_index,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.replace("\\", "/")
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out

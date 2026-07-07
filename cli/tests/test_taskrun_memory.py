import json

from typer.testing import CliRunner

from proofloop.cli import app
from proofloop.taskrun_memory import iter_task_run_records, write_task_run_memory

runner = CliRunner()


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_task_run_memory_exports_assessment_refs(tmp_repo):
    absolute_proof = tmp_repo.root / "artifacts" / "screen.png"
    assessment_path = tmp_repo.root / ".proofloop" / "task-runs" / "task_001" / "assessment.json"
    _write_json(
        assessment_path,
        {
            "id": "task_001",
            "created_at": "2026-07-07T12:00:00Z",
            "task": "Run the live checkout flow.",
            "passed": False,
            "issues": [
                {
                    "code": "mock_or_stub_completion",
                    "severity": "block",
                    "evidence": "used a stub",
                    "fix": "exercise the live path",
                }
            ],
            "transcript_path": "trace.jsonl",
            "proof_paths": ["proofs/api.log", str(absolute_proof)],
            "required_markers": ["POST /api/orders"],
            "verify_cmd": ["pytest", "-q"],
            "verify_exit_code": 1,
            "verify_log": ".proofloop/task-runs/task_001/verify.log",
            "feedback_path": ".proofloop/task-runs/task_001/feedback.md",
            "assessment_path": ".proofloop/task-runs/task_001/assessment.json",
        },
    )

    rows = list(iter_task_run_records(tmp_repo.root))

    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "task_run"
    assert row["label"] == "task_blocked"
    assert row["trace_ref"] == "trace.jsonl"
    assert row["proof_refs"] == ["proofs/api.log", "artifacts/screen.png"]
    assert row["issues"][0]["code"] == "mock_or_stub_completion"
    assert row["evidence_paths"] == [
        ".proofloop/task-runs/task_001/assessment.json",
        "trace.jsonl",
        "proofs/api.log",
        "artifacts/screen.png",
        ".proofloop/task-runs/task_001/verify.log",
        ".proofloop/task-runs/task_001/feedback.md",
    ]


def test_task_run_memory_links_loop_artifacts(tmp_repo):
    assessment_path = tmp_repo.root / ".proofloop" / "task-runs" / "task_001" / "assessment.json"
    _write_json(
        assessment_path,
        {
            "id": "task_001",
            "created_at": "2026-07-07T12:05:00Z",
            "task": "Run BTB task on the live UI",
            "passed": True,
            "issues": [],
            "transcript_path": ".proofloop/task-runs/loop_001/iteration-01-codex.jsonl",
            "proof_paths": [".proofloop/task-runs/loop_001/iteration-01-codex.stderr.log"],
            "required_markers": ["POST /api/orders"],
            "verify_cmd": ["python", "-c", "print('POST /api/orders status 200')"],
            "verify_exit_code": 0,
            "verify_log": ".proofloop/task-runs/task_001/verify.log",
            "assessment_path": ".proofloop/task-runs/task_001/assessment.json",
        },
    )
    loop_dir = tmp_repo.root / ".proofloop" / "task-runs" / "loop_001"
    _write_json(
        loop_dir / "loop.json",
        {
            "id": "loop_001",
            "passed": True,
            "iterations": [
                {
                    "iteration": 1,
                    "created_at": "2026-07-07T12:04:00Z",
                    "codex_exit_code": 0,
                    "prompt": ".proofloop/task-runs/loop_001/iteration-01-prompt.md",
                    "transcript": ".proofloop/task-runs/loop_001/iteration-01-codex.jsonl",
                    "codex_log": ".proofloop/task-runs/loop_001/iteration-01-codex.stderr.log",
                    "assessment": ".proofloop/task-runs/task_001/assessment.json",
                    "selected_task": ".proofloop/task-runs/loop_001/selected-task.json",
                    "passed": True,
                    "issues": [],
                }
            ],
            "run_dir": ".proofloop/task-runs/loop_001",
            "changelog_path": ".proofloop/task-runs/loop_001/changelog.md",
            "versions_path": ".proofloop/task-runs/loop_001/versions.jsonl",
            "final_assessment_path": ".proofloop/task-runs/task_001/assessment.json",
        },
    )

    rows = list(iter_task_run_records(tmp_repo.root))

    assert [row["id"] for row in rows] == ["task_001", "loop_001"]
    assessment_row = rows[0]
    assert assessment_row["label"] == "task_passed"
    assert assessment_row["loop_id"] == "loop_001"
    assert assessment_row["loop_iteration"] == 1
    assert ".proofloop/task-runs/loop_001/loop.json" in assessment_row["evidence_paths"]
    assert ".proofloop/task-runs/loop_001/changelog.md" in assessment_row["evidence_paths"]
    assert ".proofloop/task-runs/loop_001/iteration-01-prompt.md" in assessment_row["evidence_paths"]
    assert ".proofloop/task-runs/loop_001/selected-task.json" in assessment_row["evidence_paths"]

    loop_row = rows[1]
    assert loop_row["source"] == "task_loop"
    assert loop_row["label"] == "task_passed"
    assert loop_row["task"] == "Run BTB task on the live UI"
    assert loop_row["iterations"][0]["assessment"] == ".proofloop/task-runs/task_001/assessment.json"
    assert loop_row["iterations"][0]["selected_task"] == ".proofloop/task-runs/loop_001/selected-task.json"
    assert loop_row["proof_refs"] == [
        ".proofloop/task-runs/loop_001/iteration-01-codex.stderr.log"
    ]
    assert ".proofloop/task-runs/task_001/verify.log" in loop_row["evidence_paths"]


def test_write_task_run_memory_uses_separate_jsonl(tmp_repo):
    _write_json(
        tmp_repo.root / ".proofloop" / "task-runs" / "task_001" / "assessment.json",
        {
            "id": "task_001",
            "created_at": "2026-07-07T12:00:00Z",
            "task": "finish task",
            "passed": True,
            "issues": [],
            "assessment_path": ".proofloop/task-runs/task_001/assessment.json",
        },
    )

    count = write_task_run_memory(tmp_repo.root)

    assert count == 1
    output = tmp_repo.root / ".proofloop" / "task-run-memory.jsonl"
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["id"] == "task_001"
    assert rows[0]["label"] == "task_passed"
    assert not (tmp_repo.root / ".proofloop" / "memory.jsonl").exists()


def test_task_export_memory_cli_writes_jsonl(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    _write_json(
        tmp_repo.root / ".proofloop" / "task-runs" / "task_001" / "assessment.json",
        {
            "id": "task_001",
            "created_at": "2026-07-07T12:00:00Z",
            "task": "finish task",
            "passed": False,
            "issues": [{"code": "missing_live_evidence"}],
            "assessment_path": ".proofloop/task-runs/task_001/assessment.json",
        },
    )

    result = runner.invoke(app, ["task", "export-memory", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["rows"] == 1
    output = tmp_repo.root / ".proofloop" / "task-run-memory.jsonl"
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["label"] == "task_blocked"

import json
import sys

from typer.testing import CliRunner

from proofloop.cli import app
from proofloop.hooks import handle_hook
from proofloop.tasksetup import (
    detect_project_signals,
    ensure_agents_guidance,
    ensure_benchmark_adapter,
)

runner = CliRunner()


def _assistant_trace(text: str) -> str:
    return json.dumps({"role": "assistant", "content": text}) + "\n"


def test_task_judge_blocks_local_setup_refusal(tmp_repo, monkeypatch):
    trace = tmp_repo.write(
        "trace.jsonl",
        _assistant_trace("I cannot set up this because it requires local setup."),
    )
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        [
            "task",
            "judge",
            "--task",
            "Run a BankerToolBench task end to end.",
            "--transcript",
            str(trace),
            "--no-require-live",
        ],
    )

    assert result.exit_code == 2
    assert "local_setup_refusal" in result.output
    feedback = tmp_repo.root / ".proofloop" / "task-runs" / "task_001" / "feedback.md"
    assert feedback.is_file()
    assert "Do not stop because setup is local" in feedback.read_text()


def test_task_judge_blocks_mock_or_stub_completion(tmp_repo, monkeypatch):
    trace = tmp_repo.write(
        "trace.jsonl",
        _assistant_trace(
            "I verified this through a mocked stub and deterministic demo path."
        ),
    )
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        ["task", "judge", "--transcript", str(trace), "--no-require-live"],
    )

    assert result.exit_code == 2
    assert "mock_or_stub_completion" in result.output


def test_task_judge_passes_with_live_verifier_and_required_marker(tmp_repo, monkeypatch):
    trace = tmp_repo.write("trace.jsonl", _assistant_trace("I completed the task."))
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        [
            "task",
            "judge",
            "--transcript",
            str(trace),
            "--require-marker",
            "POST /api/orders",
            "--",
            sys.executable,
            "-c",
            "print('POST /api/orders status 200')",
        ],
    )

    assert result.exit_code == 0
    assessment = json.loads(
        (tmp_repo.root / ".proofloop" / "task-runs" / "task_001" / "assessment.json").read_text()
    )
    assert assessment["passed"] is True
    assert assessment["verify_exit_code"] == 0
    assert assessment["verify_log"].endswith("verify.log")


def test_task_judge_blocks_missing_required_marker(tmp_repo, monkeypatch):
    trace = tmp_repo.write("trace.jsonl", _assistant_trace("I completed the task."))
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        [
            "task",
            "judge",
            "--transcript",
            str(trace),
            "--require-marker",
            "POST /api/orders",
            "--",
            sys.executable,
            "-c",
            "print('GET /health status 200')",
        ],
    )

    assert result.exit_code == 2
    assert "required_live_marker_missing" in result.output


def test_task_judge_does_not_accept_assistant_only_live_marker(tmp_repo, monkeypatch):
    trace = tmp_repo.write(
        "trace.jsonl",
        _assistant_trace("I completed it live. POST /api/orders status 200"),
    )
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        [
            "task",
            "judge",
            "--transcript",
            str(trace),
            "--require-marker",
            "POST /api/orders",
        ],
    )

    assert result.exit_code == 2
    assert "required_live_marker_missing" in result.output
    assert "missing_live_evidence" in result.output


def test_blocked_task_feedback_delivers_once_through_codex_hook(tmp_repo, monkeypatch, scrubbed_env):
    trace = tmp_repo.write(
        "trace.jsonl",
        _assistant_trace("I cannot run this because it needs local setup."),
    )
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        ["task", "judge", "--transcript", str(trace), "--no-require-live"],
    )
    assert result.exit_code == 2

    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    first = handle_hook(payload, tmp_repo.root, scrubbed_env)
    assert "additionalContext" in first["hookSpecificOutput"]
    assert "Proofloop task judge feedback" in first["hookSpecificOutput"]["additionalContext"]
    assert "Do not stop because setup is local" in first["hookSpecificOutput"]["additionalContext"]

    second = handle_hook(payload, tmp_repo.root, scrubbed_env)
    assert second == {}


def test_task_setup_creates_hooks_agents_and_adapter(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    tmp_repo.write(
        "package.json",
        json.dumps(
            {
                "scripts": {"dev": "vite", "test:e2e": "playwright test"},
                "devDependencies": {"@playwright/test": "^1.0.0", "vite": "^5.0.0"},
            }
        ),
    )

    result = runner.invoke(app, ["task", "setup", "--benchmark", "bankertoolbench"])

    assert result.exit_code == 0
    assert (tmp_repo.root / ".proofloop.toml").is_file()
    assert (tmp_repo.root / ".codex" / "hooks.json").is_file()
    assert "Proofloop task loop" in (tmp_repo.root / "AGENTS.md").read_text()
    adapter = json.loads(
        (
            tmp_repo.root
            / ".proofloop"
            / "benchmark-adapters"
            / "bankertoolbench.json"
        ).read_text()
    )
    assert adapter["benchmark"] == "bankertoolbench"
    assert adapter["command_plan"]["install"] == [["npm", "install"]]
    assert adapter["startup_commands"] == [["npm", "run", "dev"]]
    assert adapter["verify_commands"] == [["npm", "run", "test:e2e"]]
    assert adapter["live_ui_api_requirements"]["requires_live_ui"] is True
    assert adapter["meta_rubric"]["name"] == "live_browser_benchmark_task"
    assert adapter["meta_rubric"]["proofloop_validates_fields"] is True
    assert "field_contract" in adapter["meta_rubric"]
    seed_ids = {
        field["field_id"] for field in adapter["meta_rubric"]["required_seed_fields"]
    }
    assert "browser_ui_exercised" in seed_ids
    assert "mock_stub_success_path_used" in seed_ids
    assert "browser" in adapter["required_live_markers"]
    assert adapter["mock_stub_rejection_signals"]
    assert "mock_stub_review" in adapter["success_evidence_schema"]["required"]
    assert any("live UI/API path" in item for item in adapter["codex_contract"])


def test_benchmark_adapter_repairs_and_refreshes_without_clobbering_custom_fields(tmp_repo):
    tmp_repo.write(
        "package.json",
        json.dumps({"scripts": {"dev": "vite", "test:e2e": "playwright test"}}),
    )
    adapter_dir = tmp_repo.root / ".proofloop" / "benchmark-adapters"
    adapter_dir.mkdir(parents=True)
    adapter_path = adapter_dir / "bankertoolbench.json"
    adapter_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "benchmark": "bankertoolbench",
                "created_at": "2026-01-01T00:00:00+00:00",
                "verify_commands": [["custom", "verify"]],
                "custom_note": "keep me",
            }
        )
        + "\n"
    )

    signals = detect_project_signals(tmp_repo.root)
    changed, path = ensure_benchmark_adapter(
        tmp_repo.root, "bankertoolbench", signals, refresh=False
    )

    assert changed is True
    assert path == adapter_path
    repaired = json.loads(adapter_path.read_text())
    assert repaired["schema_version"] == "2"
    assert repaired["created_at"] == "2026-01-01T00:00:00+00:00"
    assert repaired["custom_note"] == "keep me"
    assert repaired["verify_commands"] == [["custom", "verify"]]
    assert repaired["command_plan"]["verify"] == [["custom", "verify"]]
    assert "live_ui_api_requirements" in repaired
    assert "success_evidence_schema" in repaired

    repaired_text = adapter_path.read_text()
    changed_again, _ = ensure_benchmark_adapter(
        tmp_repo.root, "bankertoolbench", signals, refresh=False
    )
    assert changed_again is False
    assert adapter_path.read_text() == repaired_text

    refreshed, _ = ensure_benchmark_adapter(
        tmp_repo.root, "bankertoolbench", signals, refresh=True
    )

    assert refreshed is True
    refreshed_adapter = json.loads(adapter_path.read_text())
    assert refreshed_adapter["custom_note"] == "keep me"
    assert refreshed_adapter["created_at"] == "2026-01-01T00:00:00+00:00"
    assert refreshed_adapter["verify_commands"] == [["npm", "run", "test:e2e"]]
    assert refreshed_adapter["command_plan"]["verify"] == [["npm", "run", "test:e2e"]]

    refreshed_text = adapter_path.read_text()
    refreshed_again, _ = ensure_benchmark_adapter(
        tmp_repo.root, "bankertoolbench", signals, refresh=True
    )
    assert refreshed_again is False
    assert adapter_path.read_text() == refreshed_text


def test_agents_guidance_refreshes_legacy_block_idempotently(tmp_repo):
    tmp_repo.write(
        "AGENTS.md",
        "# Team guidance\n\n"
        "<!-- proofloop-task-loop -->\n"
        "## Proofloop task loop\n\n"
        "- old guidance\n\n"
        "## Existing section\n\n"
        "Keep this.\n",
    )

    changed, message = ensure_agents_guidance(tmp_repo.root)

    assert changed is True
    assert "refreshed" in message
    text = (tmp_repo.root / "AGENTS.md").read_text()
    assert "success evidence matching the adapter schema" in text
    assert "<!-- /proofloop-task-loop -->" in text
    assert "## Existing section" in text
    assert "Keep this." in text

    refreshed_text = (tmp_repo.root / "AGENTS.md").read_text()
    changed_again, _ = ensure_agents_guidance(tmp_repo.root)
    assert changed_again is False
    assert (tmp_repo.root / "AGENTS.md").read_text() == refreshed_text


def test_agents_guidance_new_file_is_idempotent(tmp_repo):
    changed, _ = ensure_agents_guidance(tmp_repo.root)

    assert changed is True
    text = (tmp_repo.root / "AGENTS.md").read_text()

    changed_again, _ = ensure_agents_guidance(tmp_repo.root)

    assert changed_again is False
    assert (tmp_repo.root / "AGENTS.md").read_text() == text


def test_task_judge_self_heals_hooks_agents_and_adapter(tmp_repo, monkeypatch):
    trace = tmp_repo.write(
        "trace.jsonl",
        _assistant_trace("I completed the task."),
    )
    monkeypatch.chdir(tmp_repo.root)

    result = runner.invoke(
        app,
        [
            "task",
            "judge",
            "--transcript",
            str(trace),
            "--no-require-live",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_repo.root / ".proofloop.toml").is_file()
    assert (tmp_repo.root / ".codex" / "hooks.json").is_file()
    assert "Proofloop task loop" in (tmp_repo.root / "AGENTS.md").read_text()
    assert (
        tmp_repo.root / ".proofloop" / "benchmark-adapters" / "bankertoolbench.json"
    ).is_file()


def test_task_loop_runs_fake_codex_to_passing_verdict(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    fake_codex = tmp_repo.write(
        "fake_codex.py",
        "import json, sys\n"
        "prompt = sys.argv[-1]\n"
        "print(json.dumps({'role': 'assistant', 'content': 'Live run complete. POST /api/orders status 200'}))\n",
    )

    result = runner.invoke(
        app,
        [
            "task",
            "loop",
            "--task",
            "Run BTB task on the live UI",
            "--benchmark",
            "bankertoolbench",
            "--require-marker",
            "POST /api/orders",
            "--codex-command",
            f'"{sys.executable}" "{fake_codex}"',
            "--max-iterations",
            "1",
            "--",
            sys.executable,
            "-c",
            "print('POST /api/orders status 200')",
        ],
    )

    assert result.exit_code == 0
    loop_dir = tmp_repo.root / ".proofloop" / "task-runs" / "loop_001"
    assert (loop_dir / "changelog.md").is_file()
    assert (loop_dir / "versions.jsonl").is_file()
    loop = json.loads((loop_dir / "loop.json").read_text())
    assert loop["passed"] is True
    assert loop["iterations"][0]["passed"] is True
    assert loop["iterations"][0]["verify_log"].endswith("verify.log")
    prompt = (loop_dir / "iteration-01-prompt.md").read_text()
    assert "Live browser benchmark meta-rubric" in prompt
    assert "browser_ui_exercised" in prompt
    assert "assistant_claim_only" in prompt


def test_task_loop_blocks_failed_codex_even_when_verifier_passes(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    fake_codex = tmp_repo.write(
        "fake_codex.py",
        "import sys\n"
        "print('')\n"
        "raise SystemExit(7)\n",
    )

    result = runner.invoke(
        app,
        [
            "task",
            "loop",
            "--task",
            "Run BTB task on the live UI",
            "--benchmark",
            "bankertoolbench",
            "--require-marker",
            "POST /api/orders",
            "--codex-command",
            f'"{sys.executable}" "{fake_codex}"',
            "--max-iterations",
            "1",
            "--",
            sys.executable,
            "-c",
            "print('POST /api/orders status 200')",
        ],
    )

    assert result.exit_code == 2
    assessment = json.loads(
        (
            tmp_repo.root
            / ".proofloop"
            / "task-runs"
            / "task_001"
            / "assessment.json"
        ).read_text()
    )
    issue_codes = {issue["code"] for issue in assessment["issues"]}
    assert "agent_execution_failed" in issue_codes
    assert assessment["agent_exit_code"] == 7


def test_task_loop_versions_record_changed_files(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo.root)
    fake_codex = tmp_repo.write(
        "fake_codex.py",
        "from pathlib import Path\n"
        "import json\n"
        "Path('feature.txt').write_text('live change')\n"
        "print(json.dumps({'role': 'assistant', 'content': 'Done.'}))\n",
    )

    result = runner.invoke(
        app,
        [
            "task",
            "loop",
            "--task",
            "Run BTB task on the live UI",
            "--benchmark",
            "bankertoolbench",
            "--require-marker",
            "POST /api/orders",
            "--codex-command",
            f'"{sys.executable}" "{fake_codex}"',
            "--max-iterations",
            "1",
            "--",
            sys.executable,
            "-c",
            "print('POST /api/orders status 200')",
        ],
    )

    assert result.exit_code == 0
    loop_dir = tmp_repo.root / ".proofloop" / "task-runs" / "loop_001"
    row = json.loads((loop_dir / "versions.jsonl").read_text().splitlines()[0])
    assert "feature.txt" in row["changed_files_since_loop_start"]
    assert "feature.txt" in (loop_dir / "changelog.md").read_text()

"""Proofloop CLI — the agent-neutral interception gate.

Exit codes:
- 0   gate passed and the child succeeded (or --no-exec)
- N   the child's exit code (127/126 when the child command is
      missing/not executable; 128 + N when the child dies to signal N)
- 2   BLOCKED by the gate (the command was never spawned)
- 3   internal proofloop error (an internal error never silently allows)
- 64  usage error (EX_USAGE) — e.g. the wrapped command was not
      separated with ' -- '
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from typer.core import TyperCommand

from . import __version__
from .agent_detect import detect_installed_agents
from .config import clear_judge_config, config_path, save_judge_config
from .envfile import parse_env_file
from .gate import EXIT_INTERNAL_ERROR, run_gate, scrub_text
from .hooks import (
    AGENTS_SNIPPET,
    PROOFLOOP_TOML_TEMPLATE,
    cursor_deny_output,
    deny_output,
    detect_deploy_stack,
    detect_extra_deploy_patterns,
    handle_cursor_hook,
    handle_hook,
)
from .memory.store import MemoryStore
from .session import now_iso, stamp
from .taskloop import (
    evaluate_task_run,
    loop_exit_code,
    run_codex_task_loop,
    task_exit_code,
)
from .taskrun_memory import TASK_RUN_MEMORY_FILE, write_task_run_memory
from .tasksetup import (
    SetupResult,
    detect_project_signals,
    ensure_agents_guidance,
    ensure_benchmark_adapter,
    load_adapter,
)

try:  # typer >= 0.16 vendors click as typer._click
    from typer._click import exceptions as click_exceptions
except ImportError:  # pragma: no cover — standalone click installs
    from click import exceptions as click_exceptions  # type: ignore[no-redef]

#: Usage errors must not collide with exit 2 (BLOCKED) — use EX_USAGE.
EX_USAGE = 64
click_exceptions.UsageError.exit_code = EX_USAGE

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Proofloop — a correctness gate for AI-written code.",
)
memory_app = typer.Typer(help="Inspect proofloop memory records.")
app.add_typer(memory_app, name="memory")
advisory_app = typer.Typer(
    help="Review advisory findings (model judgment, never blocking): "
    "approve held findings, reject wrong ones, confirm correct ones."
)
app.add_typer(advisory_app, name="advisory")
task_app = typer.Typer(
    help="Audit benchmark/task episodes for local-setup refusals and fake live runs."
)
app.add_typer(task_app, name="task")

PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}
RUN_KINDS = ("tests", "build", "lint", "typecheck")
JUDGE_PROVIDERS = ("openrouter", "anthropic", "openai")

_SENTINEL_KEY = "proofloop_has_sentinel"


class SentinelCommand(TyperCommand):
    """Records whether the raw argv contained the ``--`` separator.

    Click drops the sentinel during parsing, but without it we cannot
    tell the wrapped command's flags from our own (``proofloop guard
    deploy vercel --force`` would silently self-force-override).
    """

    def parse_args(self, ctx, args):  # type: ignore[override]
        ctx.meta[_SENTINEL_KEY] = "--" in args
        return super().parse_args(ctx, args)


def _tail_cmd(args: list[str]) -> list[str]:
    args = list(args)
    if args and args[0] == "--":
        args = args[1:]
    return args


def _require_sentinel(ctx: typer.Context, usage: str) -> None:
    """Reject wrapped commands not separated with ' -- ' (EX_USAGE)."""
    if ctx.args and not ctx.meta.get(_SENTINEL_KEY, True):
        raise click_exceptions.UsageError(
            f"separate the wrapped command with ' -- ' — usage: {usage} "
            "(without the separator, the wrapped command's flags would be "
            "parsed as proofloop's own)"
        )


def _usage_error(message: str) -> None:
    raise click_exceptions.UsageError(message)


def _store() -> MemoryStore:
    return MemoryStore(Path.cwd() / ".proofloop")


def _fail(message: str, code: int) -> None:
    typer.secho(f"proofloop: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code)


# --------------------------------------------------------------------------
# guard
# --------------------------------------------------------------------------


@app.command(context_settings=PASSTHROUGH, cls=SentinelCommand)
def guard(
    ctx: typer.Context,
    action: str = typer.Argument(..., help="The intercepted action, e.g. 'deploy'."),
    force: bool = typer.Option(
        False, "--force", help="Proceed despite failures (logged as overridden)."
    ),
    no_exec: bool = typer.Option(
        False, "--no-exec", help="Run the gate only; never spawn the command."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Print the full memory record JSON instead of panels."
    ),
    env_file: Path = typer.Option(
        None,
        "--env-file",
        help="Evaluate the env_vars check against this env file (the deploy "
        "target's environment) instead of the current shell.",
    ),
    task: str = typer.Option(
        None,
        "--task",
        help="What the change was supposed to do (enables tier-5 advisory "
        "findings; also via PROOFLOOP_TASK or [session].task).",
    ),
) -> None:
    """Gate a command: proofloop guard deploy -- <cmd...>"""
    _require_sentinel(ctx, "proofloop guard <action> -- <cmd...>")
    cmd = _tail_cmd(ctx.args)
    if not cmd and not no_exec:
        _usage_error("no command given — usage: proofloop guard <action> -- <cmd...>")
    deploy_env = None
    if env_file is not None:
        try:
            deploy_env = parse_env_file(env_file)
        except OSError as exc:
            _usage_error(f"cannot read --env-file {env_file}: {exc}")
    try:
        result = run_gate(
            Path.cwd(),
            action,
            cmd or None,
            force=force,
            no_exec=no_exec,
            json_output=json_out,
            env=dict(os.environ),
            deploy_env=deploy_env,
            task_ref=task,
        )
    except Exception as exc:  # internal error must never silently allow
        typer.secho(
            f"proofloop internal error (refusing to allow): {exc}",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(EXIT_INTERNAL_ERROR)
    raise typer.Exit(result.exit_code)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


@app.command(context_settings=PASSTHROUGH, cls=SentinelCommand)
def run(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help="tests | build | lint | typecheck"),
) -> None:
    """Run a command and stamp the session marker the gate checks.

    proofloop run tests -- pytest -q
    """
    if kind not in RUN_KINDS:
        _usage_error(f"unknown kind '{kind}' — expected one of: {', '.join(RUN_KINDS)}")
    _require_sentinel(ctx, "proofloop run <kind> -- <cmd...>")
    cmd = _tail_cmd(ctx.args)
    if not cmd:
        _usage_error("no command given — usage: proofloop run <kind> -- <cmd...>")

    root = Path.cwd()
    runs_dir = root / ".proofloop" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = runs_dir / f"{kind}-{ts}.log"

    try:
        proc = subprocess.Popen(
            cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except FileNotFoundError:
        _fail(f"command not found: {cmd[0]}", 127)
        return  # unreachable
    except PermissionError:
        _fail(f"command not executable: {cmd[0]}", 126)
        return  # unreachable
    assert proc.stdout is not None
    with log_path.open("w", encoding="utf-8") as log:
        for line in proc.stdout:
            sys.stdout.write(line)
            # Persisted output is scrubbed; the live tee stays raw.
            log.write(scrub_text(line, os.environ))
    exit_code = proc.wait()
    # A signal-killed child reports a negative returncode; map to the
    # shell convention 128 + signal BEFORE stamping so the session
    # marker and the CLI exit code both record e.g. 143, never -15.
    if exit_code < 0:
        exit_code = 128 - exit_code

    stamp(root, kind, exit_code, [scrub_text(part, os.environ) for part in cmd])
    rel_log = log_path.relative_to(root)
    typer.secho(
        f"proofloop: recorded {kind} run (exit {exit_code}) → {rel_log}",
        fg=typer.colors.GREEN if exit_code == 0 else typer.colors.RED,
    )
    raise typer.Exit(exit_code)


# --------------------------------------------------------------------------
# task judge
# --------------------------------------------------------------------------


def _ensure_task_environment(
    root: Path,
    benchmark: str,
    *,
    all_agents: bool = True,
    refresh_adapter: bool = False,
) -> SetupResult:
    result = SetupResult()
    (root / ".proofloop").mkdir(exist_ok=True)
    signals = detect_project_signals(root)
    result.signals = signals

    toml_path = root / ".proofloop.toml"
    if toml_path.exists():
        result.existing.append(".proofloop.toml")
    else:
        toml_path.write_text(
            _render_proofloop_toml(detect_extra_deploy_patterns(root)),
            encoding="utf-8",
        )
        result.changed.append(".proofloop.toml")

    for message in (
        _merge_claude_hook(root),
        _merge_cursor_hooks(root)
        if all_agents or "cursor" in detect_installed_agents(root)
        else "",
        _merge_codex_hooks(root)
        if all_agents or "codex" in detect_installed_agents(root)
        else "",
    ):
        if not message:
            continue
        if "already" in message:
            result.existing.append(message)
        elif "skipped" in message:
            result.warnings.append(message)
        else:
            result.changed.append(message)

    changed, message = ensure_agents_guidance(root)
    (result.changed if changed else result.existing).append(message)

    adapter_changed, adapter_path = ensure_benchmark_adapter(
        root, benchmark, signals, refresh=refresh_adapter
    )
    result.adapter_path = str(adapter_path.relative_to(root))
    (result.changed if adapter_changed else result.existing).append(result.adapter_path)
    return result


@task_app.command("setup")
def task_setup(
    benchmark: str = typer.Option(
        "bankertoolbench",
        "--benchmark",
        "-b",
        help="Benchmark adapter name to create/update.",
    ),
    refresh_adapter: bool = typer.Option(
        False,
        "--refresh-adapter",
        help="Rewrite an existing benchmark adapter from current repo signals.",
    ),
    all_agents: bool = typer.Option(
        True,
        "--all-agents/--detected-agents-only",
        help="Wire all supported agent hooks, or only detected agents.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print setup JSON."),
) -> None:
    """Search the repo and repair Proofloop/Codex task-loop setup."""
    result = _ensure_task_environment(
        Path.cwd(),
        benchmark,
        all_agents=all_agents,
        refresh_adapter=refresh_adapter,
    )
    if json_out:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False))
        return
    for item in result.changed:
        typer.secho(f"changed: {item}", fg=typer.colors.GREEN)
    for item in result.existing:
        typer.echo(f"existing: {item}")
    for item in result.warnings:
        typer.secho(f"warning: {item}", fg=typer.colors.YELLOW)
    typer.echo(f"adapter: {result.adapter_path}")


@task_app.command("judge", context_settings=PASSTHROUGH, cls=SentinelCommand)
def task_judge(
    ctx: typer.Context,
    task: str = typer.Option(
        None,
        "--task",
        help="Benchmark/user task under test; persisted in the assessment.",
    ),
    benchmark: str = typer.Option(
        "bankertoolbench",
        "--benchmark",
        "-b",
        help="Benchmark adapter name to repair before judging.",
    ),
    setup: bool = typer.Option(
        True,
        "--setup/--no-setup",
        help="Repair Proofloop hooks, AGENTS.md, and benchmark adapter before judging.",
    ),
    refresh_adapter: bool = typer.Option(
        False,
        "--refresh-adapter",
        help="Rewrite the benchmark adapter from current repo signals before judging.",
    ),
    transcript: Path = typer.Option(
        None,
        "--transcript",
        help="Agent transcript/session trace to audit (JSONL or plain text).",
    ),
    proof: list[Path] = typer.Option(
        [],
        "--proof",
        "-p",
        help="Proof log/file/directory to scan for live UI/API evidence.",
    ),
    require_marker: list[str] = typer.Option(
        [],
        "--require-marker",
        "-m",
        help="Case-insensitive marker that must appear in transcript/proof/verify output.",
    ),
    no_require_live: bool = typer.Option(
        False,
        "--no-require-live",
        help="Do not fail solely because no live UI/API evidence was supplied.",
    ),
    verify_timeout: int = typer.Option(
        600,
        "--verify-timeout",
        min=1,
        help="Seconds before the verifier command times out.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Print the task assessment JSON.",
    ),
) -> None:
    """Audit an agent benchmark run and emit corrective feedback.

    Optional verifier command goes after `--`:

    proofloop task judge --transcript trace.jsonl -m "POST /api" -- npm run e2e
    """
    if ctx.args and not ctx.meta.get(_SENTINEL_KEY, True):
        _require_sentinel(ctx, "proofloop task judge [options] -- <verify-cmd...>")
    if setup:
        _ensure_task_environment(
            Path.cwd(),
            benchmark,
            refresh_adapter=refresh_adapter,
        )
    verify_cmd = _tail_cmd(ctx.args)
    assessment = evaluate_task_run(
        Path.cwd(),
        task=task,
        transcript_path=transcript,
        proof_paths=proof,
        verify_cmd=verify_cmd,
        required_markers=require_marker,
        require_live=not no_require_live,
        verify_timeout_seconds=verify_timeout,
        env=dict(os.environ),
    )

    if json_out:
        typer.echo(json.dumps(assessment.to_dict(), ensure_ascii=False))
    elif assessment.passed:
        typer.secho(
            f"proofloop: task judge passed ({assessment.id}) -> "
            f"{assessment.assessment_path}",
            fg=typer.colors.GREEN,
        )
    else:
        typer.secho(
            f"proofloop: task judge blocked ({assessment.id}) -> "
            f"{assessment.feedback_path}",
            fg=typer.colors.RED,
        )
        for issue in assessment.issues:
            typer.echo(f"- {issue.code}: {issue.evidence}")
        typer.echo("Give the feedback file to the agent, then rerun the live verification.")
    raise typer.Exit(task_exit_code(assessment))


@task_app.command("loop", context_settings=PASSTHROUGH, cls=SentinelCommand)
def task_loop(
    ctx: typer.Context,
    task: str = typer.Option(
        ...,
        "--task",
        help="Benchmark/user task to run through Codex until Proofloop verdict.",
    ),
    benchmark: str = typer.Option(
        "bankertoolbench",
        "--benchmark",
        "-b",
        help="Benchmark adapter name.",
    ),
    max_iterations: int = typer.Option(
        3,
        "--max-iterations",
        min=1,
        help="Maximum Codex/judge repair iterations.",
    ),
    require_marker: list[str] = typer.Option(
        [],
        "--require-marker",
        "-m",
        help="Live evidence marker that must appear before pass.",
    ),
    codex_command: str = typer.Option(
        None,
        "--codex-command",
        help='Codex command prefix; default: "codex exec --json".',
    ),
    refresh_adapter: bool = typer.Option(
        False,
        "--refresh-adapter",
        help="Refresh adapter before running the loop.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print loop JSON."),
) -> None:
    """Set up, run Codex, judge traces, and repeat until a task verdict."""
    if ctx.args and not ctx.meta.get(_SENTINEL_KEY, True):
        _require_sentinel(ctx, "proofloop task loop --task ... -- <verify-cmd...>")
    root = Path.cwd()
    setup = _ensure_task_environment(root, benchmark, refresh_adapter=refresh_adapter)
    adapter_path = root / (setup.adapter_path or "")
    adapter = load_adapter(adapter_path)
    verify_cmd = _tail_cmd(ctx.args)
    if not verify_cmd:
        verify_commands = adapter.get("verify_commands") or []
        if verify_commands and isinstance(verify_commands[0], list):
            verify_cmd = [str(part) for part in verify_commands[0]]
    result = run_codex_task_loop(
        root,
        task=task,
        benchmark=benchmark,
        adapter_path=adapter_path if adapter_path.is_file() else None,
        verify_cmd=verify_cmd,
        required_markers=require_marker,
        codex_cmd=codex_command,
        max_iterations=max_iterations,
        env=dict(os.environ),
    )
    if json_out:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False))
    elif result.passed:
        typer.secho(
            f"proofloop: task loop passed ({result.id}) -> {result.changelog_path}",
            fg=typer.colors.GREEN,
        )
    else:
        typer.secho(
            f"proofloop: task loop blocked after {len(result.iterations)} iteration(s) "
            f"({result.id}) -> {result.changelog_path}",
            fg=typer.colors.RED,
        )
    raise typer.Exit(loop_exit_code(result))


@task_app.command("export-memory")
def task_export_memory(
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="JSONL output path; default: .proofloop/task-run-memory.jsonl.",
    ),
    include_loops: bool = typer.Option(
        True,
        "--include-loops/--assessments-only",
        help="Include loop-level records as well as task assessment rows.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print result JSON."),
) -> None:
    """Export task-loop outcomes as additive training records."""
    root = Path.cwd()
    rows = write_task_run_memory(root, output, include_loops=include_loops)
    output_path = output or (root / ".proofloop" / TASK_RUN_MEMORY_FILE)
    if json_out:
        typer.echo(
            json.dumps(
                {
                    "rows": rows,
                    "output": str(output_path),
                    "include_loops": include_loops,
                },
                ensure_ascii=False,
            )
        )
        return
    typer.secho(
        f"proofloop: exported {rows} task-run memory row(s) -> {output_path}",
        fg=typer.colors.GREEN,
    )


# --------------------------------------------------------------------------
# resolve / confirm
# --------------------------------------------------------------------------


@app.command()
def resolve(
    record_id: str = typer.Argument(..., metavar="ID"),
    status: str = typer.Option(..., "--status", help="accepted | false_positive"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Label whether a block was correct (training label)."""
    if status not in ("accepted", "false_positive"):
        _usage_error("--status must be 'accepted' or 'false_positive'")
    ok = _store().update_resolution(
        record_id, {"status": status, "note": note or None, "at": now_iso()}
    )
    if not ok:
        _fail(f"record {record_id} not found", 1)
    typer.echo(f"{record_id} resolved: {status}")


@app.command()
def confirm(
    record_id: str = typer.Argument(..., metavar="ID"),
    outcome: str = typer.Option(..., "--outcome", help="shipped | rolled_back"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Attach the post-deploy ground truth to a record."""
    if outcome not in ("shipped", "rolled_back"):
        _usage_error("--outcome must be 'shipped' or 'rolled_back'")
    ok = _store().update_resolution(
        record_id,
        {"status": "confirmed", "outcome": outcome, "note": note or None, "at": now_iso()},
    )
    if not ok:
        _fail(f"record {record_id} not found", 1)
    typer.echo(f"{record_id} confirmed: {outcome}")


# --------------------------------------------------------------------------
# advisory — approve / reject / confirm one finding (chk_NNN#i)
# --------------------------------------------------------------------------


def _parse_advisory_ref(ref: str) -> tuple[str, int]:
    record_id, sep, index = ref.partition("#")
    if not sep or not index.isdigit() or not record_id:
        _usage_error(
            f"advisory ids look like chk_012#0 (record id '#' finding index), got {ref!r}"
        )
    return record_id, int(index)


def _get_advisory(store: MemoryStore, record_id: str, index: int) -> dict:
    record = store.get(record_id)
    if record is None:
        _fail(f"record {record_id} not found", 1)
    if index >= len(record.advisories):
        _fail(
            f"{record_id} has {len(record.advisories)} advisory finding(s) — "
            f"no #{index}",
            1,
        )
    return record.advisories[index]


@advisory_app.command("approve")
def advisory_approve(ref: str = typer.Argument(..., metavar="ID", help="e.g. chk_012#0")) -> None:
    """Approve a HELD finding — delivered to the agent on the next deploy event."""
    record_id, index = _parse_advisory_ref(ref)
    store = _store()
    entry = _get_advisory(store, record_id, index)
    if entry.get("delivery") != "held":
        _fail(
            f"advisory {ref} is not held (delivery: {entry.get('delivery')}) — "
            "only held findings await approval",
            1,
        )
    store.label_advisory(record_id, index, delivery="staged")
    typer.echo(f"{ref} approved — will reach the agent on the next deploy event")


@advisory_app.command("reject")
def advisory_reject(ref: str = typer.Argument(..., metavar="ID", help="e.g. chk_012#0")) -> None:
    """Reject a finding: labels it, stops it re-firing, retracts if delivered.

    Three effects: (1) a rejected label on the record (training signal);
    (2) the finding's signature never re-fires or grounds future findings;
    (3) if the agent already saw it, a retraction note goes out on the next
    deploy event. What the agent already read cannot be unread — effects
    1–2 are immediate and permanent, effect 3 lands on the next event.
    """
    record_id, index = _parse_advisory_ref(ref)
    store = _store()
    entry = _get_advisory(store, record_id, index)
    delivered = entry.get("delivery") in ("injected", "sent")
    store.label_advisory(
        record_id, index, label="rejected", retraction="staged" if delivered else None
    )
    message = f"{ref} rejected — this finding will not re-fire"
    if delivered:
        message += "; a retraction note goes to the agent on the next deploy event"
    typer.echo(message)


@advisory_app.command("confirm")
def advisory_confirm(ref: str = typer.Argument(..., metavar="ID", help="e.g. chk_012#0")) -> None:
    """Label a finding correct — repeat confirmations surface it in
    `proofloop memory stats` as a candidate deterministic check."""
    record_id, index = _parse_advisory_ref(ref)
    store = _store()
    _get_advisory(store, record_id, index)
    store.label_advisory(record_id, index, label="confirmed")
    typer.echo(f"{ref} confirmed")


# --------------------------------------------------------------------------
# login / logout — BYOK judge key onboarding
# --------------------------------------------------------------------------


def _mask_key(key: str) -> str:
    """Render a key as ``sk-…last4`` — never the full secret."""
    if len(key) <= 8:
        return "…" + key[-2:] if len(key) >= 2 else "…"
    return f"{key[:3]}…{key[-4:]}"


def _verify_login(console: Console, provider: str, api_key: str, model: str | None) -> None:
    """Best-effort live check — never fails the command."""
    from .checks.base import CheckResult, Evidence
    from .judge import AnthropicJudge, JudgeInput, OpenAIJudge, OpenRouterJudge

    adapters = {
        "openrouter": OpenRouterJudge,
        "anthropic": AnthropicJudge,
        "openai": OpenAIJudge,
    }
    judge = adapters[provider](api_key=api_key, model=model)
    probe = JudgeInput(
        action="deploy",
        repo_id="proofloop-login-check",
        failures=[
            CheckResult(
                name="env_vars",
                passed=False,
                failure_class="missing_env_var",
                evidence=[Evidence(file="app.py", line=1, detail="EXAMPLE_KEY")],
                fix_hint="set EXAMPLE_KEY",
            )
        ],
        git_summary="",
    )
    output = judge.diagnose(probe)  # falls back to deterministic on any error
    if not output.model_id.startswith("deterministic/"):
        console.print(f"✓ key works ({output.model_id})")
    else:
        console.print(
            "  (saved, but couldn't verify — offline or network error)", style="dim"
        )


@app.command()
def login(
    provider: str = typer.Option(
        None, "--provider", help="openrouter | anthropic | openai (default openrouter)."
    ),
    api_key: str = typer.Option(
        None, "--api-key", help="API key — skips the prompts; never echoed or logged."
    ),
    model: str = typer.Option(
        None, "--model", help="Model id (blank = the provider's default)."
    ),
    no_verify: bool = typer.Option(
        False, "--no-verify", help="Skip the best-effort live key check."
    ),
) -> None:
    """Store an LLM API key so the judge writes explanations (BYOK).

    Interactive by default; pass --api-key to run non-interactively. The key
    is written to ~/.config/proofloop/config.toml (0600), never echoed.
    """
    console = Console(highlight=False)
    interactive = api_key is None

    if provider is None and interactive:
        provider = typer.prompt(
            "Provider (openrouter/anthropic/openai)", default="openrouter"
        )
    provider = (provider or "openrouter").strip().lower()
    if provider not in JUDGE_PROVIDERS:
        _usage_error(f"--provider must be one of: {', '.join(JUDGE_PROVIDERS)}")

    if api_key is None:
        api_key = typer.prompt("API key", hide_input=True)
    if not api_key:
        _usage_error("no API key provided")

    if model is None and interactive:
        entered = typer.prompt(
            "Model (blank = provider default)", default="", show_default=False
        )
        model = entered or None
    if model is not None:
        model = model.strip() or None

    path = save_judge_config(provider, api_key, model=model, env=os.environ)
    console.print(f"✓ saved {provider} key → {path} (mode 0600)")
    console.print(f"  key: {_mask_key(api_key)}")

    if not no_verify:
        _verify_login(console, provider, api_key, model)


@app.command()
def logout() -> None:
    """Remove the stored LLM key (the judge falls back to deterministic)."""
    console = Console(highlight=False)
    removed = clear_judge_config(env=os.environ)
    if removed:
        console.print(f"✓ removed {removed} judge config → {config_path(os.environ)}")
    else:
        console.print("no stored judge config to remove", style="dim")


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------


@memory_app.command("list")
def memory_list() -> None:
    """List all memory records."""
    table = Table(title="proofloop memory", box=box.SIMPLE_HEAD)
    table.add_column("id", style="bold")
    table.add_column("created")
    table.add_column("action")
    table.add_column("agent")
    table.add_column("gate")
    table.add_column("failure classes")
    table.add_column("recalled_from")
    table.add_column("resolution")
    count = 0
    for record in _store().iter_records():
        count += 1
        classes = ", ".join(sorted(record.failure_classes())) or "—"
        resolution = (record.resolution or {}).get("status", "—") if record.resolution else "—"
        table.add_row(
            record.id,
            record.created_at,
            record.action_intercepted,
            record.agent_source,
            "[green]passed[/green]" if record.gate_passed else "[red]blocked[/red]",
            classes,
            record.recalled_from or "—",
            resolution,
        )
    console = Console()
    if count == 0:
        console.print("[dim]no records yet — run `proofloop guard <action> -- <cmd>`[/dim]")
        return
    console.print(table)


@memory_app.command("show")
def memory_show(record_id: str = typer.Argument(..., metavar="ID")) -> None:
    """Print one full record as JSON."""
    record = _store().get(record_id)
    if record is None:
        _fail(f"record {record_id} not found", 1)
        return  # unreachable
    typer.echo(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))


@memory_app.command("export")
def memory_export(
    labeled_only: bool = typer.Option(
        False, "--labeled-only", help="Only rows with a resolution label."
    ),
    failure_class: str = typer.Option(
        None, "--failure-class", help="Only records with this failure class."
    ),
    dedupe: bool = typer.Option(
        False, "--dedupe", help="Keep only the last record per inputs_hash."
    ),
    output: Path = typer.Option(
        None, "-o", "--output", help="Write JSONL here instead of stdout."
    ),
) -> None:
    """Export training-ready JSONL (each record plus a computed `label`)."""
    from .memory.export import export_rows

    rows = list(
        export_rows(
            _store(),
            labeled_only=labeled_only,
            failure_class=failure_class,
            dedupe=dedupe,
        )
    )
    if not rows:
        # stdout stays pipeline-safe (empty); the friendly note goes to stderr.
        sys.stderr.write("proofloop: no matching memory records to export\n")
        return
    # Plain writes only — Rich would wrap long lines and corrupt JSONL.
    if output is not None:
        with output.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        sys.stderr.write(f"proofloop: wrote {len(rows)} row(s) → {output}\n")
    else:
        for row in rows:
            sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")


@memory_app.command("stats")
def memory_stats(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Dataset health metrics + judge cost-ledger aggregation."""
    from .memory.export import stats

    store = _store()
    data = stats(store, store.root / "ledger.jsonl")
    if json_out:
        sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
        return
    console = Console()
    if data["records"] == 0:
        console.print("[dim]no records yet — run `proofloop guard <action> -- <cmd>`[/dim]")
        return
    table = Table(title="proofloop memory stats", box=box.SIMPLE_HEAD)
    table.add_column("metric", style="bold")
    table.add_column("value")
    table.add_row("records", str(data["records"]))
    table.add_row("blocked / passed", f"{data['blocked']} / {data['passed']}")
    table.add_row(
        "failure classes",
        ", ".join(f"{k}={v}" for k, v in sorted(data["failure_classes"].items())) or "—",
    )
    table.add_row(
        "labels",
        ", ".join(f"{k}={v}" for k, v in sorted(data["labels"].items())) or "—",
    )
    table.add_row("recall hit rate", f"{data['recall_hit_rate']:.0%}")
    table.add_row("auto-resolve rate", f"{data['auto_resolve_rate']:.0%}")
    table.add_row(
        "gate duration",
        f"mean {data['gate_duration_ms']['mean']:.0f} ms · "
        f"p95 {data['gate_duration_ms']['p95']} ms",
    )
    table.add_row(
        "agents",
        ", ".join(f"{k}={v}" for k, v in sorted(data["agents"].items())) or "—",
    )
    advisories = data["advisories"]
    if advisories["total"]:
        table.add_row(
            "advisories",
            f"{advisories['total']} finding(s) · "
            + ", ".join(f"{k}={v}" for k, v in sorted(advisories["by_delivery"].items()))
            + " · labels: "
            + ", ".join(f"{k}={v}" for k, v in sorted(advisories["by_label"].items())),
        )
    ledger = data["ledger"]
    table.add_row(
        "judge spend",
        f"${ledger['total_cost_usd']:.4f} over {ledger['calls']} call(s)",
    )
    console.print(table)
    candidates = advisories["graduation_candidates"]
    if candidates:
        console.print(
            "\n[bold]Candidate deterministic checks[/bold] — advisory findings "
            "confirmed repeatedly; write the file:line check and enforcement "
            "moves to the deterministic core:"
        )
        for candidate in candidates:
            console.print(
                f"  ×{candidate['confirmed']} confirmed [{candidate['kind']}]: "
                f"{candidate['concern']} ({', '.join(candidate['ids'])})"
            )


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def _merge_claude_hook(root: Path) -> str:
    """Write the PreToolUse hook into .claude/settings.json (merge, don't clobber)."""
    settings_dir = root / ".claude"
    settings_path = settings_dir / "settings.json"
    data: dict = {}
    if settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text() or "{}")
        except json.JSONDecodeError:
            return f"skipped {settings_path} (existing file is not valid JSON — not clobbering)"
    hooks = data.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    already = any(
        "proofloop hook" in hook.get("command", "")
        for entry in pre
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )
    if already:
        return f"{settings_path} already wired (proofloop hook present)"
    pre.append(
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "proofloop hook"}],
        }
    )
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n")
    return f"wrote PreToolUse hook → {settings_path}"


def _merge_codex_hooks(root: Path) -> str:
    """Write the PreToolUse hook into .codex/hooks.json (merge, don't clobber).

    Codex's hooks engine mirrors Claude Code's shape (same event, matcher
    and payload). Never write config.toml — tomllib is read-only and a
    rewrite would clobber user comments/format; hooks.json only.
    """
    hooks_dir = root / ".codex"
    hooks_path = hooks_dir / "hooks.json"
    data: dict = {}
    if hooks_path.is_file():
        try:
            data = json.loads(hooks_path.read_text() or "{}")
        except json.JSONDecodeError:
            return f"skipped {hooks_path} (existing file is not valid JSON — not clobbering)"
    hooks = data.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    already = any(
        "proofloop hook" in hook.get("command", "")
        for entry in pre
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )
    if already:
        return f"{hooks_path} already wired (proofloop hook present)"
    pre.append(
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "proofloop hook --agent codex"}],
        }
    )
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n")
    return f"wrote PreToolUse hook → {hooks_path}"


def _merge_cursor_hooks(root: Path) -> str:
    """Write the beforeShellExecution hook into .cursor/hooks.json.

    Cursor hooks have NO per-hook matcher — every shell command fires the
    hook; deploy matching stays in Python where .proofloop.toml's
    deploy_patterns_extra applies. Entry shape is flat: {"command": ...}.
    """
    hooks_dir = root / ".cursor"
    hooks_path = hooks_dir / "hooks.json"
    data: dict = {}
    if hooks_path.is_file():
        try:
            data = json.loads(hooks_path.read_text() or "{}")
        except json.JSONDecodeError:
            return f"skipped {hooks_path} (existing file is not valid JSON — not clobbering)"
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    before = hooks.setdefault("beforeShellExecution", [])
    already = any(
        isinstance(entry, dict) and "proofloop hook" in entry.get("command", "")
        for entry in before
    )
    if already:
        return f"{hooks_path} already wired (proofloop hook present)"
    before.append({"command": "proofloop hook --agent cursor"})
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n")
    return f"wrote beforeShellExecution hook → {hooks_path}"


def _venv_path_warning() -> str | None:
    """Warn when the proofloop on PATH lives inside a virtualenv.

    GUI-launched agents (Cursor especially) don't inherit a shell-activated
    venv PATH, so the hook command would silently not resolve.
    """
    import shutil

    resolved = shutil.which("proofloop")
    in_venv = sys.prefix != sys.base_prefix
    if resolved and ("/.venv/" in resolved or "/venv/" in resolved or in_venv):
        return (
            "proofloop resolves inside a virtualenv — GUI-launched agents may "
            "not inherit that PATH. Install it user-wide (pipx install "
            "proofloop) or put the absolute path in the hook files."
        )
    return None


def _render_proofloop_toml(extra_patterns: list[str]) -> str:
    """Base template plus an active ``deploy_patterns_extra`` block when
    ``proofloop init`` detected repo-local deploy entrypoints.

    Patterns without a single quote are written as TOML single-quoted
    literals (no escaping needed for regex backslashes); the appended key
    lands under ``[hook]``, the template's last section. A pattern
    containing a single quote can't sit in a literal string (TOML has no
    escaping inside ``'...'``), so it's emitted as a basic string with
    JSON escaping — valid TOML for these inputs.
    """
    if not extra_patterns:
        return PROOFLOOP_TOML_TEMPLATE
    block = [
        "",
        "# Auto-detected repo-local deploy entrypoints (safe to edit):",
        "deploy_patterns_extra = [",
    ]
    for p in extra_patterns:
        if "'" in p:
            block.append(f"  {json.dumps(p)},")
        else:
            block.append(f"  '{p}',")
    block.append("]")
    return PROOFLOOP_TOML_TEMPLATE + "\n".join(block) + "\n"


@app.command()
def init(
    all_agents: bool = typer.Option(
        False, "--all-agents", help="Wire hooks for all supported agents, detected or not."
    ),
) -> None:
    """Set up proofloop in this repo: .proofloop/, agent hooks, config."""
    root = Path.cwd()
    console = Console(highlight=False)

    (root / ".proofloop").mkdir(exist_ok=True)
    console.print("✓ created .proofloop/")

    agents = detect_installed_agents(root)
    console.print(
        f"✓ detected agents: {', '.join(agents) if agents else 'none'}"
    )

    stack = detect_deploy_stack(root)
    if stack:
        console.print(
            f"✓ detected deploy targets: {', '.join(stack)} "
            "(covered by the built-in patterns)"
        )
    else:
        console.print(
            "✓ no known deploy config found — built-in patterns still cover "
            "the common CLIs"
        )
    extras = detect_extra_deploy_patterns(root)

    toml_path = root / ".proofloop.toml"
    if toml_path.exists():
        console.print(f"✓ {toml_path.name} already exists (left untouched)")
        if extras:
            console.print(
                f"  › tip: {len(extras)} repo-local deploy script(s) detected — "
                "add them under [hook].deploy_patterns_extra to gate them"
            )
    else:
        toml_path.write_text(_render_proofloop_toml(extras))
        if extras:
            console.print(
                f"✓ wrote {toml_path.name} "
                f"(seeded {len(extras)} repo-local deploy pattern(s))"
            )
        else:
            console.print(f"✓ wrote {toml_path.name} template")

    console.print(f"✓ {_merge_claude_hook(root)}")
    if all_agents or "cursor" in agents:
        console.print(f"✓ {_merge_cursor_hooks(root)}")
    if all_agents or "codex" in agents:
        console.print(f"✓ {_merge_codex_hooks(root)}")
        console.print(
            "  › Codex loads project hooks only after you trust this folder — "
            "run `codex` once and accept the prompt. Codex's streaming exec "
            "path can bypass hooks, so the AGENTS.md snippet below is still "
            "required for full Codex coverage."
        )
    warning = _venv_path_warning()
    if warning and (all_agents or "cursor" in agents or "codex" in agents):
        console.print(f"  › warning: {warning}", style="yellow")

    console.print(
        "\nAdd this to your AGENTS.md / CLAUDE.md so every agent routes deploys "
        "through the gate:\n"
    )
    console.print(AGENTS_SNIPPET)


# --------------------------------------------------------------------------
# hook (hidden) — Claude Code PreToolUse adapter
# --------------------------------------------------------------------------


@app.command(hidden=True)
def hook(
    agent: str = typer.Option(
        "claude", "--agent", help="claude | codex | cursor (payload/output schema)."
    ),
) -> None:
    """Read a hook JSON event from stdin; emit deny JSON or no decision.

    Bare `proofloop hook` stays byte-compatible with existing Claude Code
    settings.json files (default agent: claude).
    """
    agent = (agent or "claude").strip().lower()
    if agent not in ("claude", "codex", "cursor"):
        _usage_error("--agent must be one of: claude, codex, cursor")
    raw = sys.stdin.read()
    internal_error_reason = (
        "Proofloop hit an internal error while gating this command and "
        "fails closed: {exc}. Run `proofloop guard deploy --no-exec` "
        "for details. Fix these, then re-run the original command."
    )

    if agent == "cursor":
        try:
            payload = json.loads(raw) if raw.strip() else {}
            output = handle_cursor_hook(payload, Path.cwd(), dict(os.environ))
        except Exception as exc:  # fail CLOSED — and it must be exit 2:
            # Cursor blocks on exit 2 but FAILS OPEN on any other non-zero,
            # so an uncaught traceback (exit 1) would allow a deploy while
            # the gate is broken.
            sys.stderr.write(f"proofloop hook internal error — failing closed: {exc}\n")
            print(json.dumps(cursor_deny_output(internal_error_reason.format(exc=exc))))
            raise typer.Exit(2)
        print(json.dumps(output))
        return

    try:
        payload = json.loads(raw) if raw.strip() else {}
        env = dict(os.environ)
        if agent == "codex":
            # setdefault: never clobber a user-exported PROOFLOOP_AGENT_SOURCE.
            env.setdefault("PROOFLOOP_AGENT_SOURCE", "codex")
        output = handle_hook(payload, Path.cwd(), env)
    except Exception as exc:  # fail CLOSED — never silently allow
        sys.stderr.write(f"proofloop hook internal error — failing closed: {exc}\n")
        print(json.dumps(deny_output(internal_error_reason.format(exc=exc))))
        raise typer.Exit(2)
    print(json.dumps(output))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

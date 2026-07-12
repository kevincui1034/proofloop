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
            data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
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
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
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
            data = json.loads(hooks_path.read_text(encoding="utf-8") or "{}")
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
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
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
            data = json.loads(hooks_path.read_text(encoding="utf-8") or "{}")
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
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
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
        toml_path.write_text(_render_proofloop_toml(extras), encoding="utf-8")
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

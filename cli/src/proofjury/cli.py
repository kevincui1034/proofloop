"""Proofjury CLI — the agent-neutral interception gate.

Exit codes:
- 0   gate passed and the child succeeded (or --no-exec)
- N   the child's exit code (127/126 when the child command is
      missing/not executable; 128 + N when the child dies to signal N)
- 2   BLOCKED by the gate (the command was never spawned)
- 3   internal proofjury error (an internal error never silently allows)
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
    PROOFJURY_TOML_TEMPLATE,
    cursor_deny_output,
    deny_output,
    detect_deploy_stack,
    detect_extra_deploy_patterns,
    handle_cursor_hook,
    handle_hook,
)
from .memory.store import MemoryStore
from .session import (
    MAX_MARKER_AGE_HOURS,
    load_session,
    marker_status,
    now_iso,
    stamp,
    worktree_digest,
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
    help="Proofjury — a correctness gate for AI-written code.",
)
memory_app = typer.Typer(help="Inspect proofjury memory records.")
app.add_typer(memory_app, name="memory")
advisory_app = typer.Typer(
    help="Review advisory findings (model judgment, never blocking): "
    "approve held findings, reject wrong ones, confirm correct ones."
)
app.add_typer(advisory_app, name="advisory")

PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}
RUN_KINDS = ("tests", "build", "lint", "typecheck")
JUDGE_PROVIDERS = ("openrouter", "anthropic", "openai")

_SENTINEL_KEY = "proofjury_has_sentinel"


class SentinelCommand(TyperCommand):
    """Records whether the raw argv contained the ``--`` separator.

    Click drops the sentinel during parsing, but without it we cannot
    tell the wrapped command's flags from our own (``proofjury guard
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
            "parsed as proofjury's own)"
        )


def _usage_error(message: str) -> None:
    raise click_exceptions.UsageError(message)


def _store() -> MemoryStore:
    return MemoryStore(Path.cwd() / ".proofjury")


def _fail(message: str, code: int) -> None:
    typer.secho(f"proofjury: {message}", err=True, fg=typer.colors.RED)
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
        "findings; also via PROOFJURY_TASK or [session].task).",
    ),
) -> None:
    """Gate a command: proofjury guard deploy -- <cmd...>"""
    _require_sentinel(ctx, "proofjury guard <action> -- <cmd...>")
    cmd = _tail_cmd(ctx.args)
    if not cmd and not no_exec:
        _usage_error("no command given — usage: proofjury guard <action> -- <cmd...>")
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
            f"proofjury internal error (refusing to allow): {exc}",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(EXIT_INTERNAL_ERROR)
    try:
        # Best-effort post-run sync — firewalled like the advisory judge:
        # it must never change the exit code, output, or spawn behavior.
        from .sync import sync_after_gate

        sync_after_gate(Path.cwd(), os.environ)
    except Exception:
        pass
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

    proofjury run tests -- pytest -q
    """
    if kind not in RUN_KINDS:
        _usage_error(f"unknown kind '{kind}' — expected one of: {', '.join(RUN_KINDS)}")
    _require_sentinel(ctx, "proofjury run <kind> -- <cmd...>")
    cmd = _tail_cmd(ctx.args)
    if not cmd:
        _usage_error("no command given — usage: proofjury run <kind> -- <cmd...>")

    root = Path.cwd()
    runs_dir = root / ".proofjury" / "runs"
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
        f"proofjury: recorded {kind} run (exit {exit_code}) → {rel_log}",
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
    `proofjury memory stats` as a candidate deterministic check."""
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
        repo_id="proofjury-login-check",
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
    is written to ~/.config/proofjury/config.toml (0600), never echoed.
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
# connect / disconnect / sync — opt-in hosted dashboard
# --------------------------------------------------------------------------


@app.command()
def connect(
    endpoint: str = typer.Option(
        None,
        "--endpoint",
        help="Dashboard API base (dev/test override; default app.proofjury.com).",
    ),
    no_open: bool = typer.Option(
        False, "--no-open", help="Don't try to open the approval page in a browser."
    ),
) -> None:
    """Connect this machine to your hosted dashboard (device-code flow).

    Prints a URL + code; approve it in the browser while logged in. The
    token lands in ~/.config/proofjury/config.toml (0600). After that,
    every gate run best-effort syncs its scrubbed record — sync never
    blocks, slows, or fails the gate. Undo with `proofjury disconnect`;
    web-made advisory labels reach your agent on the next gate run.
    """
    import time as time_module

    from .config import DEFAULT_SYNC_ENDPOINT, save_sync_config
    from .sync import SyncClient, drain, repo_id_of

    console = Console(highlight=False)
    base = (
        os.environ.get("PROOFJURY_SYNC_URL") or endpoint or DEFAULT_SYNC_ENDPOINT
    ).rstrip("/")
    client = SyncClient(None, base)
    try:
        code = client.request_device_code()
    except Exception as exc:
        _fail(f"cannot reach {base}: {exc}", 1)

    user_code = code["user_code"]
    approve_url = f"{code['verification_uri']}?code={user_code}"
    console.print(f"Visit [bold]{code['verification_uri']}[/bold]")
    console.print(f"and enter code [bold]{user_code}[/bold]")
    if not no_open:
        try:  # best-effort convenience only
            import webbrowser

            webbrowser.open(approve_url)
        except Exception:
            pass

    interval = float(code.get("interval", 5))
    deadline = time_module.monotonic() + float(code.get("expires_in", 900))
    console.print("waiting for approval…", style="dim")
    while time_module.monotonic() < deadline:
        time_module.sleep(interval)
        try:
            result = client.poll_device_token(code["device_code"])
        except Exception:
            continue  # transient network error — keep polling
        status = result.get("status")
        if status == "pending":
            continue
        if status == "slow_down":
            interval += 2
            continue
        if status == "ok":
            path = save_sync_config(
                result["token"],
                result.get("token_id", ""),
                endpoint=base,
                env=os.environ,
            )
            login_name = result.get("user_login") or "you"
            console.print(f"✓ connected as {login_name} → {path} (mode 0600)")
            console.print(f"  token: {_mask_key(result['token'])}")
            # First drain, so the repo shows up immediately (best-effort).
            store = _store()
            repo_id = repo_id_of(store)
            if repo_id is not None:
                try:
                    pushed = drain(
                        store, SyncClient(result["token"], base), repo_id, limit=None
                    )
                    if pushed:
                        console.print(f"  pushed {pushed} existing record(s)")
                except Exception:
                    pass  # auto-sync will retry after the next gate run
            return
        _fail(f"device code {status} — run `proofjury connect` again", 1)
    _fail("approval timed out — run `proofjury connect` again", 1)


@app.command()
def disconnect() -> None:
    """Disconnect from the hosted dashboard and revoke this machine's token."""
    from .config import clear_sync_config, resolve_sync
    from .sync import SyncClient

    console = Console(highlight=False)
    settings = resolve_sync(os.environ)
    if settings is not None:
        try:  # best-effort server-side revoke; local clear happens regardless
            SyncClient(settings["token"], settings["endpoint"]).revoke()
        except Exception:
            pass
    removed = clear_sync_config(env=os.environ)
    if removed is not None:
        console.print(f"✓ disconnected → {config_path(os.environ)}")
    else:
        console.print("not connected", style="dim")


@app.command("sync")
def sync_cmd(
    status_only: bool = typer.Option(
        False, "--status", help="Show sync state without touching the network."
    ),
) -> None:
    """Push unsynced gate records and pull web-made labels — manually.

    Exit 0 even on network failure: sync must never be a failing gate in
    scripts. Auto-sync already runs after each gate; this drains everything.
    """
    from .config import resolve_sync
    from .sync import (
        SyncClient,
        drain,
        load_state,
        pending_count,
        pull_labels_and_apply,
        repo_id_of,
    )

    console = Console(highlight=False)
    settings = resolve_sync(os.environ)
    store = _store()

    if status_only:
        if settings is None:
            console.print("sync: disabled (run `proofjury connect`)", style="dim")
            return
        state = load_state(store.root)
        console.print(f"sync: enabled → {settings['endpoint']}")
        console.print(
            f"  pending records: {pending_count(store)} · "
            f"label cursor: {state.get('label_cursor', 0)}"
        )
        return

    if settings is None:
        console.print("sync: disabled (run `proofjury connect`)", style="dim")
        return
    repo_id = repo_id_of(store)
    if repo_id is None:
        console.print("nothing to sync (no gate records yet)", style="dim")
        return
    client = SyncClient(settings["token"], settings["endpoint"])
    pulled = 0
    try:
        pulled = pull_labels_and_apply(store, client, repo_id)
    except Exception as exc:
        console.print(f"  (label pull failed: {exc})", style="dim")
    try:
        pushed = drain(store, client, repo_id, limit=None)
    except Exception as exc:
        console.print(f"  (push failed: {exc})", style="dim")
        console.print(
            f"pushed 0, pulled {pulled} label event(s) — will retry next run"
        )
        return
    console.print(f"pushed {pushed}, pulled {pulled} label event(s)")


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------


@memory_app.command("list")
def memory_list() -> None:
    """List all memory records."""
    table = Table(title="proofjury memory", box=box.SIMPLE_HEAD)
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
        console.print("[dim]no records yet — run `proofjury guard <action> -- <cmd>`[/dim]")
        return
    console.print(table)


@memory_app.command("repos")
def memory_repos() -> None:
    """List the repos cross-repo memory recall can see (user-level registry)."""
    from .memory.registry import load_registry

    repos = load_registry(os.environ)["repos"]
    console = Console()
    if not repos:
        console.print(
            "[dim]no repos registered yet — every `proofjury guard` run "
            "registers its repo (disable with [memory] cross_repo = false)[/dim]"
        )
        return
    table = Table(title="proofjury memory repos", box=box.SIMPLE_HEAD)
    table.add_column("repo", style="bold")
    table.add_column("store")
    table.add_column("last seen")
    table.add_column("records")
    for path_str, entry in sorted(
        repos.items(), key=lambda item: str(item[1].get("last_seen", "")), reverse=True
    ):
        alive = (Path(path_str) / "memory.jsonl").is_file()
        table.add_row(
            str(entry.get("repo_id", "?")),
            path_str,
            str(entry.get("last_seen", "—")),
            "[green]present[/green]" if alive else "[red]missing[/red]",
        )
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
        sys.stderr.write("proofjury: no matching memory records to export\n")
        return
    # Plain writes only — Rich would wrap long lines and corrupt JSONL.
    if output is not None:
        with output.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        sys.stderr.write(f"proofjury: wrote {len(rows)} row(s) → {output}\n")
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
    data = stats(store, store.root / "ledger.jsonl", env=os.environ)
    if json_out:
        sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
        return
    console = Console()
    if data["records"] == 0:
        console.print("[dim]no records yet — run `proofjury guard <action> -- <cmd>`[/dim]")
        return
    table = Table(title="proofjury memory stats", box=box.SIMPLE_HEAD)
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
    cross_repo = data["cross_repo"]
    if cross_repo["registered_repos"] or cross_repo["recall_hits"]:
        table.add_row(
            "cross-repo recall",
            f"{cross_repo['registered_repos']} registered repo(s) · "
            f"{cross_repo['recall_hits']} hit(s)",
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
# status
# --------------------------------------------------------------------------


def _hook_file_wired(path: Path) -> bool | None:
    """True when a hook file references ``proofjury hook``; None when the
    file is missing or unparseable. Structure-agnostic walk so it covers
    the Claude/Codex nested shape and Cursor's flat entries alike."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return None

    def walk(node: object) -> bool:
        if isinstance(node, dict):
            cmd = node.get("command")
            if isinstance(cmd, str) and "proofjury hook" in cmd:
                return True
            return any(walk(v) for v in node.values())
        if isinstance(node, list):
            return any(walk(v) for v in node)
        return False

    return walk(data)


def _suggest_test_command(root: Path) -> str:
    """Cheap guess at this repo's test command for printed hints."""
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            if isinstance(scripts, dict) and "test" in scripts:
                return "npm test"
        except (json.JSONDecodeError, OSError):
            pass
    if any(
        (root / marker).exists()
        for marker in ("pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg")
    ):
        return "pytest"
    return "<your test command>"


_MARKER_STATE_TEXT = {
    "stale_age": f"stale (older than {MAX_MARKER_AGE_HOURS}h) — re-run to re-stamp",
    "stale_digest": "code changed since the stamp — re-run to re-stamp",
    "failed": "last run FAILED — the gate treats it as not run",
}


@app.command()
def status() -> None:
    """Gate readiness for this repo: setup, hooks, PATH, run stamps, memory.

    Informational only — always exits 0 and never changes state.
    """
    root = Path.cwd()
    console = Console(highlight=False)

    console.print("[bold]Setup[/bold]")
    setup_items = [
        (".proofjury/", (root / ".proofjury").is_dir()),
        (".proofjury.toml", (root / ".proofjury.toml").is_file()),
    ]
    agents_md = root / "AGENTS.md"
    setup_items.append(
        (
            "AGENTS.md gate instructions",
            agents_md.is_file()
            and AGENTS_MARKER_START in agents_md.read_text(encoding="utf-8"),
        )
    )
    for name, ok in setup_items:
        if ok:
            console.print(f"  ✓ {name}")
        else:
            console.print(f"  ✗ {name} missing — run: proofjury init", style="yellow")

    console.print("\n[bold]Hooks[/bold]")
    detected = detect_installed_agents(root)
    hook_files = [
        ("claude", root / ".claude" / "settings.json"),
        ("cursor", root / ".cursor" / "hooks.json"),
        ("codex", root / ".codex" / "hooks.json"),
    ]
    for agent, path in hook_files:
        wired = _hook_file_wired(path)
        tag = " (detected)" if agent in detected else ""
        if wired:
            console.print(f"  ✓ {agent}{tag}: {path.relative_to(root)} wired")
        elif agent in detected or wired is False:
            console.print(
                f"  ✗ {agent}{tag}: not wired — run: proofjury init", style="yellow"
            )
        else:
            console.print(f"  · {agent}: not detected", style="dim")

    console.print("\n[bold]PATH[/bold]")
    warning = _path_resolution_warning()
    if warning:
        console.print(f"  ✗ {warning}", style="yellow")
    else:
        console.print("  ✓ proofjury resolves user-wide")

    console.print("\n[bold]Gate readiness[/bold]")
    session = load_session(root)
    digest = worktree_digest(root)
    for kind in RUN_KINDS:
        state, marker = marker_status(session, kind, digest)
        if state == "fresh":
            console.print(f"  ✓ {kind}: fresh (stamped {marker['ran_at']})")
        elif state == "missing":
            if kind == "tests":
                console.print(
                    "  ✗ tests: NOT STAMPED — the next deploy will block on "
                    "tests_not_run; run: proofjury run tests -- "
                    f"{_suggest_test_command(root)}",
                    style="yellow",
                )
            else:
                console.print(f"  · {kind}: not stamped", style="dim")
        else:
            console.print(
                f"  ✗ {kind}: {_MARKER_STATE_TEXT[state]}; run: proofjury run "
                f"{kind} -- <cmd>",
                style="yellow",
            )

    console.print("\n[bold]Memory[/bold]")
    if (root / ".proofjury").is_dir():
        count = sum(1 for _ in _store().iter_records())
        console.print(f"  {count} record(s) in .proofjury/memory.jsonl")
    else:
        console.print("  no store yet", style="dim")


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
        "proofjury hook" in hook.get("command", "")
        for entry in pre
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )
    if already:
        return f"{settings_path} already wired (proofjury hook present)"
    pre.append(
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "proofjury hook"}],
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
        "proofjury hook" in hook.get("command", "")
        for entry in pre
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )
    if already:
        return f"{hooks_path} already wired (proofjury hook present)"
    pre.append(
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "proofjury hook --agent codex"}],
        }
    )
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"wrote PreToolUse hook → {hooks_path}"


def _merge_cursor_hooks(root: Path) -> str:
    """Write the beforeShellExecution hook into .cursor/hooks.json.

    Cursor hooks have NO per-hook matcher — every shell command fires the
    hook; deploy matching stays in Python where .proofjury.toml's
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
        isinstance(entry, dict) and "proofjury hook" in entry.get("command", "")
        for entry in before
    )
    if already:
        return f"{hooks_path} already wired (proofjury hook present)"
    before.append({"command": "proofjury hook --agent cursor"})
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"wrote beforeShellExecution hook → {hooks_path}"


AGENTS_MARKER_START = "<!-- proofjury:start -->"
AGENTS_MARKER_END = "<!-- proofjury:end -->"


def _agents_block() -> str:
    return f"{AGENTS_MARKER_START}\n{AGENTS_SNIPPET}{AGENTS_MARKER_END}"


def _merge_marker_block(path: Path, create: bool) -> str | None:
    """Write/refresh the marker-delimited gate snippet in one instructions file.

    Between-marker content is replaced on every run so snippet upgrades
    flow through re-running ``proofjury init``. Returns a status line, or
    None when the file is intentionally left alone (missing with
    ``create=False``, or a CLAUDE.md that imports AGENTS.md).
    """
    block = _agents_block()
    if not path.is_file():
        if not create:
            return None
        path.write_text(block + "\n", encoding="utf-8")
        return f"wrote gate instructions → {path.name}"
    text = path.read_text(encoding="utf-8")
    has_start = AGENTS_MARKER_START in text
    has_end = AGENTS_MARKER_END in text
    if has_start and has_end:
        start = text.index(AGENTS_MARKER_START)
        end = text.index(AGENTS_MARKER_END) + len(AGENTS_MARKER_END)
        if end <= start:
            return f"skipped {path.name} (proofjury marker block is mangled — not clobbering)"
        updated = text[:start] + block + text[end:]
        if updated == text:
            return f"{path.name} already wired (gate instructions present)"
        path.write_text(updated, encoding="utf-8")
        return f"refreshed gate instructions → {path.name}"
    if has_start or has_end:
        return f"skipped {path.name} (proofjury marker block is mangled — not clobbering)"
    if not create and "@AGENTS.md" in text:
        return f"{path.name} imports AGENTS.md (left untouched)"
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + block + "\n"
    path.write_text(text, encoding="utf-8")
    return f"wrote gate instructions → {path.name}"


def _merge_agents_snippet(root: Path) -> list[str]:
    """Write the gate snippet into AGENTS.md (created if missing) and, when
    it already exists and doesn't import AGENTS.md, CLAUDE.md too."""
    lines = []
    for name, create in (("AGENTS.md", True), ("CLAUDE.md", False)):
        status = _merge_marker_block(root / name, create=create)
        if status:
            lines.append(status)
    return lines


def _ensure_gitignore(root: Path) -> str | None:
    """Ignore .proofjury/ (session stamps, memory, proof dirs are runtime
    state, not source). Line-based check so `.proofjury.toml` entries don't
    mask it; only touches repos that actually use git."""
    if not (root / ".git").exists():
        return None
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        entries = {line.strip() for line in text.splitlines()}
        if entries & {".proofjury/", ".proofjury", "/.proofjury/", "/.proofjury"}:
            return ".gitignore already covers .proofjury/"
        if text and not text.endswith("\n"):
            text += "\n"
        gitignore.write_text(text + ".proofjury/\n", encoding="utf-8")
        return "added .proofjury/ to .gitignore"
    gitignore.write_text(".proofjury/\n", encoding="utf-8")
    return "wrote .gitignore (.proofjury/ runtime state stays local)"


def _path_resolution_warning() -> str | None:
    """Warn when the hook files' bare ``proofjury hook`` command won't
    resolve for GUI-launched agents: not on PATH at all, resolved from
    uvx's ephemeral cache (gone after this run), or resolved inside a
    virtualenv whose PATH GUI-launched agents don't inherit.
    """
    import shutil

    fix = (
        "install it user-wide (`uv tool install proofjury` or "
        "`pipx install proofjury`) so the hook command resolves everywhere"
    )
    resolved = shutil.which("proofjury")
    if resolved is None:
        return (
            "proofjury is not on PATH — the hook files reference "
            f"`proofjury hook`, which will not resolve; {fix}."
        )
    norm = resolved.replace("\\", "/")
    if "/uv/" in norm and "archive-" in norm:
        return (
            f"proofjury resolves from uvx's ephemeral cache ({resolved}) — "
            f"it disappears after this run; {fix}."
        )
    in_venv = sys.prefix != sys.base_prefix
    if "/.venv/" in norm or "/venv/" in norm or in_venv:
        return (
            "proofjury resolves inside a virtualenv — GUI-launched agents "
            f"may not inherit that PATH; {fix}."
        )
    return None


def _render_proofjury_toml(extra_patterns: list[str]) -> str:
    """Base template plus an active ``deploy_patterns_extra`` block when
    ``proofjury init`` detected repo-local deploy entrypoints.

    Patterns without a single quote are written as TOML single-quoted
    literals (no escaping needed for regex backslashes); the appended key
    lands under ``[hook]``, the template's last section. A pattern
    containing a single quote can't sit in a literal string (TOML has no
    escaping inside ``'...'``), so it's emitted as a basic string with
    JSON escaping — valid TOML for these inputs.
    """
    if not extra_patterns:
        return PROOFJURY_TOML_TEMPLATE
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
    return PROOFJURY_TOML_TEMPLATE + "\n".join(block) + "\n"


@app.command()
def init(
    all_agents: bool = typer.Option(
        False, "--all-agents", help="Wire hooks for all supported agents, detected or not."
    ),
    no_agents_md: bool = typer.Option(
        False,
        "--no-agents-md",
        help="Don't write the gate snippet into AGENTS.md/CLAUDE.md; print it instead.",
    ),
) -> None:
    """Set up proofjury in this repo: .proofjury/, agent hooks, config."""
    root = Path.cwd()
    console = Console(highlight=False)

    (root / ".proofjury").mkdir(exist_ok=True)
    console.print("✓ created .proofjury/")
    gitignore_note = _ensure_gitignore(root)
    if gitignore_note:
        console.print(f"✓ {gitignore_note}")

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

    toml_path = root / ".proofjury.toml"
    if toml_path.exists():
        console.print(f"✓ {toml_path.name} already exists (left untouched)")
        if extras:
            console.print(
                f"  › tip: {len(extras)} repo-local deploy script(s) detected — "
                "add them under [hook].deploy_patterns_extra to gate them"
            )
    else:
        toml_path.write_text(_render_proofjury_toml(extras), encoding="utf-8")
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
            "path can bypass hooks, so the AGENTS.md gate instructions are "
            "still required for full Codex coverage."
        )
    warning = _path_resolution_warning()
    if warning:
        console.print(f"  › warning: {warning}", style="yellow")

    snippet_fallback = no_agents_md
    if not no_agents_md:
        for line in _merge_agents_snippet(root):
            console.print(f"✓ {line}")
            if "not clobbering" in line:
                snippet_fallback = True
    if snippet_fallback:
        console.print(
            "\nAdd this to your AGENTS.md / CLAUDE.md so every agent routes "
            "deploys through the gate:\n"
        )
        console.print(AGENTS_SNIPPET)

    console.print("\nNext:")
    console.print(
        f"  1. proofjury run tests -- {_suggest_test_command(root)}"
        "   # stamp a test run — the first deploy blocks without one"
    )
    console.print(
        "  2. deploy normally — the hook gates deploy-shaped commands automatically"
    )
    console.print("  3. proofjury status   # check gate readiness anytime")


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

    Bare `proofjury hook` stays byte-compatible with existing Claude Code
    settings.json files (default agent: claude).
    """
    agent = (agent or "claude").strip().lower()
    if agent not in ("claude", "codex", "cursor"):
        _usage_error("--agent must be one of: claude, codex, cursor")
    raw = sys.stdin.read()
    internal_error_reason = (
        "Proofjury hit an internal error while gating this command and "
        "fails closed: {exc}. Run `proofjury guard deploy --no-exec` "
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
            sys.stderr.write(f"proofjury hook internal error — failing closed: {exc}\n")
            print(json.dumps(cursor_deny_output(internal_error_reason.format(exc=exc))))
            raise typer.Exit(2)
        print(json.dumps(output))
        return

    try:
        payload = json.loads(raw) if raw.strip() else {}
        env = dict(os.environ)
        if agent == "codex":
            # setdefault: never clobber a user-exported PROOFJURY_AGENT_SOURCE.
            env.setdefault("PROOFJURY_AGENT_SOURCE", "codex")
        output = handle_hook(payload, Path.cwd(), env)
    except Exception as exc:  # fail CLOSED — never silently allow
        sys.stderr.write(f"proofjury hook internal error — failing closed: {exc}\n")
        print(json.dumps(deny_output(internal_error_reason.format(exc=exc))))
        raise typer.Exit(2)
    print(json.dumps(output))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

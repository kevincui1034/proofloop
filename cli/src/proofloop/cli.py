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
from .gate import EXIT_INTERNAL_ERROR, run_gate, scrub_text
from .hooks import (
    AGENTS_SNIPPET,
    PROOFLOOP_TOML_TEMPLATE,
    deny_output,
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

PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}
RUN_KINDS = ("tests", "build", "lint", "typecheck")

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
) -> None:
    """Gate a command: proofloop guard deploy -- <cmd...>"""
    _require_sentinel(ctx, "proofloop guard <action> -- <cmd...>")
    cmd = _tail_cmd(ctx.args)
    if not cmd and not no_exec:
        _usage_error("no command given — usage: proofloop guard <action> -- <cmd...>")
    try:
        result = run_gate(
            Path.cwd(),
            action,
            cmd or None,
            force=force,
            no_exec=no_exec,
            json_output=json_out,
            env=dict(os.environ),
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


@app.command()
def init() -> None:
    """Set up proofloop in this repo: .proofloop/, agent hooks, config."""
    root = Path.cwd()
    console = Console(highlight=False)

    (root / ".proofloop").mkdir(exist_ok=True)
    console.print("✓ created .proofloop/")

    agents = detect_installed_agents(root)
    console.print(
        f"✓ detected agents: {', '.join(agents) if agents else 'none'}"
    )

    toml_path = root / ".proofloop.toml"
    if toml_path.exists():
        console.print(f"✓ {toml_path.name} already exists (left untouched)")
    else:
        toml_path.write_text(PROOFLOOP_TOML_TEMPLATE)
        console.print(f"✓ wrote {toml_path.name} template")

    console.print(f"✓ {_merge_claude_hook(root)}")

    console.print(
        "\nAdd this to your AGENTS.md / CLAUDE.md so every agent routes deploys "
        "through the gate:\n"
    )
    console.print(AGENTS_SNIPPET)


# --------------------------------------------------------------------------
# hook (hidden) — Claude Code PreToolUse adapter
# --------------------------------------------------------------------------


@app.command(hidden=True)
def hook() -> None:
    """Read a PreToolUse JSON event from stdin; emit deny JSON or no decision."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
        output = handle_hook(payload, Path.cwd(), dict(os.environ))
    except Exception as exc:  # fail CLOSED — never silently allow
        sys.stderr.write(f"proofloop hook internal error — failing closed: {exc}\n")
        print(
            json.dumps(
                deny_output(
                    "Proofloop hit an internal error while gating this command and "
                    f"fails closed: {exc}. Run `proofloop guard deploy --no-exec` "
                    "for details. Fix these, then re-run the original command."
                )
            )
        )
        raise typer.Exit(2)
    print(json.dumps(output))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

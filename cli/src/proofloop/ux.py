"""Block/allow UX — this IS the product's face.

Rendering respects NO_COLOR and non-tty output automatically (rich), so
transcripts captured through a pipe are plain text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich import box
from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:  # pragma: no cover
    from .checks.base import CheckResult
    from .memory.schema import MemoryRecord


def get_console() -> Console:
    return Console(highlight=False)


def _evidence_table(failures: list["CheckResult"]) -> Table:
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, expand=False)
    table.add_column("Check", style="bold", no_wrap=True)
    table.add_column("Class", style="red", no_wrap=True)
    table.add_column("Evidence", overflow="fold")
    for result in failures:
        table.add_row(result.name, result.failure_class or "—", result.evidence_str() or "—")
    return table


def render_blocked(
    console: Console,
    record: "MemoryRecord",
    failures: list["CheckResult"],
    recalled: "MemoryRecord | None",
    cmd: list[str] | None,
    fix_steps: list[str],
    forced: bool = False,
) -> None:
    action = record.action_intercepted.upper()
    parts: list = [_evidence_table(failures)]

    parts.append(Padding(Text(record.diagnosis, style="default"), (1, 0, 0, 0)))

    if fix_steps:
        fix_lines = Text()
        fix_lines.append("\nFix:\n", style="bold green")
        for i, step in enumerate(fix_steps, start=1):
            fix_lines.append(f"  {i}. {step}\n", style="green")
        parts.append(fix_lines)

    if recalled is not None:
        parts.append(
            Panel(
                Text(
                    f"↩ Recalled from {recalled.id} — this failure was diagnosed before "
                    f"in this repo ({recalled.created_at}).",
                    style="yellow",
                ),
                border_style="yellow",
                box=box.ROUNDED,
            )
        )

    if forced:
        parts.append(
            Text(
                "⚠ OVERRIDDEN with --force — executing anyway. "
                "The override is logged in the record's resolution.",
                style="bold yellow",
            )
        )

    title = f"⛔ {action} BLOCKED — proofloop" if not forced else f"⚠ {action} GATE FAILED (forced) — proofloop"
    if cmd:
        subtitle = f"blocked command: {' '.join(cmd)}" if not forced else f"forcing: {' '.join(cmd)}"
    else:
        subtitle = None
    console.print(
        Panel(
            Group(*parts),
            title=title,
            subtitle=subtitle,
            border_style="red" if not forced else "yellow",
            box=box.HEAVY,
            padding=(1, 2),
        )
    )
    exit_note = "exit 2" if not forced else "exit follows the command"
    console.print(
        Text(
            f"record {record.id} → .proofloop/memory.jsonl · proof: {record.context_ref} "
            f"· --force to override (logged) · {exit_note}",
            style="dim",
        )
    )


def render_allowed(
    console: Console,
    record: "MemoryRecord",
    results: list["CheckResult"],
    cmd: list[str] | None,
    no_exec: bool,
) -> None:
    ran = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    summary = Text()
    summary.append(f"All {len(ran)} checks passed", style="bold green")
    if skipped:
        summary.append(
            f" ({len(skipped)} skipped: {', '.join(r.name for r in skipped)})",
            style="dim",
        )
    summary.append(".\n")
    for result in ran:
        summary.append(f"  ✓ {result.name}\n", style="green")
    if record.resolves:
        summary.append(
            f"\n✦ Resolves {record.resolves} — the failure diagnosed there is now fixed.",
            style="cyan",
        )
    if cmd and not no_exec:
        body_title = f"✅ GATE PASSED — executing: {' '.join(cmd)}"
    elif cmd:
        body_title = f"✅ GATE PASSED — clear to run: {' '.join(cmd)} (--no-exec)"
    else:
        body_title = "✅ GATE PASSED — proofloop"
    console.print(
        Panel(
            summary,
            title=body_title,
            border_style="green",
            box=box.HEAVY,
            padding=(1, 2),
        )
    )
    console.print(
        Text(
            f"record {record.id} → .proofloop/memory.jsonl · proof: {record.context_ref}",
            style="dim",
        )
    )

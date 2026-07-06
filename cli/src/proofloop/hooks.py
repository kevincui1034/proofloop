"""Claude Code PreToolUse adapter.

Reads the hook JSON from stdin and matches the shell command against
deploy-command patterns. The hook only ever NARROWS permissions, never
widens them:

- Non-deploy commands (and anything it cannot parse as a deploy) get NO
  decision — an empty ``{}`` output — so Claude Code's normal permission
  flow applies untouched. The hook never auto-approves.
- Deploy-shaped commands are gated (``--no-exec``). Failures produce a
  "deny" with a STRUCTURED, agent-actionable payload — failed checks,
  file:line evidence, exact fix steps — so the agent can self-correct
  instead of stalling on a bare denial. A PASSING gate also emits no
  decision: the user's normal permission flow still makes the final call.
- ``proofloop`` invocations themselves are never re-gated (the inner
  command of ``proofloop guard deploy -- ./deploy.sh`` would otherwise
  double-run the gate and duplicate records).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Mapping

from .context import load_config
from .gate import GateResult, run_gate
from .judge.deterministic import compile_fix_steps

#: Shell commands matching any of these regexes are treated as deploys.
#: Script invocations (./deploy, deploy.sh) are anchored to the
#: command-invocation position (start of the command line or right after
#: ``&&``/``||``/``;``/``|``) so read commands like ``cat deploy.sh`` or
#: ``ls ../deployments`` never match.
DEFAULT_DEPLOY_PATTERNS = [
    r"vercel\s+--prod",
    r"vercel\s+deploy",
    r"fly\s+deploy",
    r"railway\s+up",
    r"netlify\s+deploy",
    r"git push\s+.*\b(prod|production|release)\b",
    r"(?:^|&&|\|\||;|\|)\s*(?:bash\s+|sh\s+)?\.?/?[\w./-]*deploy\.sh\b",
    r"(?:^|&&|\|\||;|\|)\s*\./[\w./-]*deploy\b",
]

FINAL_INSTRUCTION = "Fix these, then re-run the original command."

AGENTS_SNIPPET = """\
## Deploy safety — Proofloop gate (required)

Before ANY deploy/release/production-affecting command, route it through
`proofloop guard deploy -- <exact command>`. If BLOCKED (exit 2): read the
evidence, apply the listed fixes, re-run the gate. Never use `--force`
unless the human explicitly instructs it. Run tests via
`proofloop run tests -- <test cmd>` — this is how the gate knows tests ran.
"""

PROOFLOOP_TOML_TEMPLATE = """\
# Proofloop configuration — https://proofloop.dev
# All sections are optional; sensible defaults apply.

[commands]
# Commands the gate expects to have seen run for this worktree
# (stamped via `proofloop run <kind> -- <cmd>`).
# build = "npm run build"
# lint = "ruff check ."
# typecheck = "mypy ."

[hook]
# Shell commands matching any of these regexes are treated as deploys
# and routed through the gate by the Claude Code PreToolUse hook.
# Script invocations are anchored to the command position so reads
# (`cat deploy.sh`) are not intercepted.
deploy_patterns = [
  'vercel\\s+--prod',
  'vercel\\s+deploy',
  'fly\\s+deploy',
  'railway\\s+up',
  'netlify\\s+deploy',
  'git push\\s+.*\\b(prod|production|release)\\b',
  '(?:^|&&|\\|\\||;|\\|)\\s*(?:bash\\s+|sh\\s+)?\\.?/?[\\w./-]*deploy\\.sh\\b',
  '(?:^|&&|\\|\\||;|\\|)\\s*\\./[\\w./-]*deploy\\b',
]
"""

#: Leading VAR=value assignments before the actual command word.
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+")


def get_deploy_patterns(config: dict) -> list[str]:
    hook_cfg = config.get("hook") or {}
    patterns = hook_cfg.get("deploy_patterns")
    if isinstance(patterns, list) and patterns:
        return [str(p) for p in patterns]
    return DEFAULT_DEPLOY_PATTERNS


def compile_deploy_patterns(
    patterns: list[str],
    source: str = ".proofloop.toml [hook].deploy_patterns",
) -> list[re.Pattern]:
    """Compile deploy patterns, dropping invalid ones with a warning.

    A config typo must never lock the agent out of the shell: bad
    patterns are skipped (one stderr line each), and if EVERY configured
    pattern is invalid we fall back to DEFAULT_DEPLOY_PATTERNS.
    """
    compiled: list[re.Pattern] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            sys.stderr.write(
                f"proofloop: ignoring invalid deploy pattern {pattern!r} "
                f"from {source}: {exc}\n"
            )
    if not compiled:
        compiled = [re.compile(p) for p in DEFAULT_DEPLOY_PATTERNS]
    return compiled


def is_deploy_command(command: str, patterns: list) -> bool:
    """``patterns`` may be regex strings or pre-compiled patterns."""
    return any(re.search(pattern, command) for pattern in patterns)


def _first_command_token(command: str) -> str:
    rest = command.lstrip()
    while True:
        match = _ENV_ASSIGN_RE.match(rest)
        if match is None:
            break
        rest = rest[match.end():]
    parts = rest.split(None, 1)
    return parts[0] if parts else ""


def is_proofloop_invocation(command: str) -> bool:
    """True when the command itself is a proofloop call.

    Re-gating ``proofloop guard deploy -- ./deploy.sh`` (whose inner
    command matches the deploy patterns) would double-run the gate and
    duplicate memory records.
    """
    first = _first_command_token(command)
    return first == "proofloop" or Path(first).name == "proofloop"


def _hook_output(decision: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def no_decision_output() -> dict:
    """No permission decision: the normal permission flow applies.

    Emitting "allow" here would BYPASS Claude Code's permission system
    and auto-approve the command — the hook must never do that.
    """
    return {}


def deny_output(reason: str) -> dict:
    return _hook_output("deny", reason)


def build_deny_reason(result: GateResult) -> str:
    """Structured, agent-actionable denial payload."""
    record = result.record
    lines = [
        f"⛔ Proofloop BLOCKED this deploy command (record {record.id}, exit 2).",
        "",
        "Failed checks:",
    ]
    for failure in result.failures:
        lines.append(
            f"- {failure.name} → {failure.failure_class}: {failure.evidence_str()}"
        )
    lines += ["", f"Diagnosis: {record.diagnosis}", "", "Fix steps:"]
    fix_steps = compile_fix_steps(result.failures)
    for i, step in enumerate(fix_steps, start=1):
        lines.append(f"{i}. {step}")
    if result.recalled is not None:
        lines += [
            "",
            f"Memory: recalled from {result.recalled.id} — the same failure was "
            "diagnosed before in this repo.",
        ]
    lines += ["", FINAL_INSTRUCTION]
    return "\n".join(lines)


def handle_hook(payload: dict, root: Path, env: Mapping[str, str]) -> dict:
    """Process one PreToolUse event; returns the hook output JSON dict.

    Returns ``{}`` (no decision) for everything except a deploy-shaped
    command that fails the gate, which gets a structured "deny".
    """
    try:
        tool_input = payload.get("tool_input") or {}
        command = tool_input.get("command") or ""
        if not isinstance(command, str) or not command.strip():
            return no_decision_output()
        if is_proofloop_invocation(command):
            return no_decision_output()  # never re-gate proofloop itself
        config = load_config(root)
        patterns = compile_deploy_patterns(get_deploy_patterns(config))
        if not is_deploy_command(command, patterns):
            return no_decision_output()
    except Exception:
        # Could not establish that this is a deploy command — stay out of
        # the decision and let the normal permission flow handle it.
        return no_decision_output()

    # The command matched a valid deploy pattern: the gate decides. Any
    # error past this point fails CLOSED (cli.hook denies on exception).
    result = run_gate(
        root,
        "deploy",
        cmd=command.split(),
        no_exec=True,
        env=dict(env),
        render=False,
    )
    if result.failures:
        return deny_output(build_deny_reason(result))
    # Gate passed: still no decision — auto-approving would silently
    # disable the user's Bash permission prompts for deploys.
    return no_decision_output()

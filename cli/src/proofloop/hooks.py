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

import json
import re
import sys
from pathlib import Path
from typing import Mapping

from .context import load_config
from .gate import GateResult, run_gate
from .judge.deterministic import compile_fix_steps

# Start of a shell command: line start, or right after a separator (; | &,
# which covers && and ||), allowing a leading `sudo`, VAR=value assignments,
# and npx/bunx-style launchers. Anchoring every tool pattern to this position
# means a tool name inside a quoted string, a commit message, or a file
# argument (`cat wrangler.toml`, `git commit -m "add docker push"`) never
# counts as a deploy — only an actual invocation does.
_CMD = (
    r"(?:^|[\n;|&])\s*"
    r"(?:sudo\s+)?"
    r"(?:[A-Za-z_]\w*=\S+\s+)*"
    r"(?:(?:npx|bunx|pnpm\s+dlx|yarn\s+dlx)\s+)?"
)


def _cmd(pattern: str) -> str:
    """Anchor a tool pattern to a shell command-invocation position."""
    return _CMD + pattern


#: Shell commands matching any of these regexes are treated as deploys. Tool
#: patterns are anchored to the command-invocation position (see ``_CMD``);
#: the two script patterns keep their own equivalent anchor so reads like
#: ``cat deploy.sh`` or ``ls ../deployments`` never match. Covers the common
#: deploy surfaces out of the box — extend with ``deploy_patterns_extra`` or
#: replace with ``deploy_patterns`` in ``.proofloop.toml [hook]``.
DEFAULT_DEPLOY_PATTERNS = [
    # PaaS / static hosts
    _cmd(r"vercel\s+(?:--prod\b|deploy\b)"),
    _cmd(r"netlify\s+deploy\b"),
    _cmd(r"(?:fly|flyctl)\s+deploy\b"),
    _cmd(r"railway\s+up\b"),
    _cmd(r"wrangler\s+(?:pages\s+)?(?:deploy|publish)\b"),
    _cmd(r"render\s+deploys?\s+create\b"),
    _cmd(r"git\s+push\s+heroku\b"),
    # cloud providers
    _cmd(r"sam\s+deploy\b"),
    _cmd(r"cdk\s+deploy\b"),
    _cmd(r"aws\s+cloudformation\s+deploy\b"),
    _cmd(r"gcloud\s+(?:run|app|functions)\s+deploy\b"),
    _cmd(r"gcloud\s+builds\s+submit\b"),
    # containers / orchestration
    _cmd(r"kubectl\s+(?:apply|rollout)\b"),
    _cmd(r"helm\s+(?:install|upgrade)\b"),
    _cmd(r"docker\s+(?:push|stack\s+deploy)\b"),
    # infrastructure as code
    _cmd(r"(?:terraform|tofu)\s+apply\b"),
    _cmd(r"pulumi\s+up\b"),
    # framework / release CLIs
    _cmd(r"(?:serverless|sls)\s+deploy\b"),
    _cmd(r"sst\s+deploy\b"),
    _cmd(r"kamal\s+(?:deploy|redeploy)\b"),
    _cmd(r"cap\s+\w+\s+deploy\b"),
    # generic release scripts
    _cmd(r"(?:npm|pnpm|yarn|bun)\s+run\s+(?:deploy|release|ship|publish)\b"),
    _cmd(r"(?:make|just)\s+(?:deploy|release|ship|publish)\b"),
    # git push to a prod/production/release branch or remote
    _cmd(r"git\s+push\b.*\b(?:prod|production|release)\b"),
    # explicit deploy scripts, anchored so `cat deploy.sh` never matches
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
# Shell commands matching any of these regexes are treated as deploys and
# routed through the gate by the Claude Code PreToolUse hook. Proofloop ships
# defaults for Vercel, Netlify, Fly, Railway, Cloudflare (wrangler), Heroku,
# AWS (sam/cdk/cloudformation), GCP (gcloud), Kubernetes (kubectl/helm),
# Docker, Terraform/Pulumi, Serverless/SST, Kamal, Capistrano, npm/make/just
# release scripts, and ./deploy.sh — so most repos need nothing here.
#
# ADD to the built-in defaults (recommended — keeps every default pattern):
# deploy_patterns_extra = ['(?:^|[;&|])\\s*bin/release\\b']
#
# REPLACE the defaults entirely (advanced — you then own the whole list):
# deploy_patterns = ['^make ship$']
"""

#: Leading VAR=value assignments before the actual command word.
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+")


def get_deploy_patterns(config: dict) -> list[str]:
    """Resolve deploy-command patterns from ``.proofloop.toml [hook]``.

    ``deploy_patterns_extra`` ADDS to the built-in defaults (recommended —
    you keep Vercel/Fly/wrangler/etc. and add your own). ``deploy_patterns``
    fully REPLACES the defaults (advanced — you own the whole list). Both may
    be set: extras are appended to the override base. Order is preserved and
    duplicates removed.
    """
    hook_cfg = config.get("hook") or {}
    override = hook_cfg.get("deploy_patterns")
    extra = hook_cfg.get("deploy_patterns_extra")
    if isinstance(override, list) and override:
        base = [str(p) for p in override]
    else:
        base = list(DEFAULT_DEPLOY_PATTERNS)
    if isinstance(extra, list):
        base += [str(p) for p in extra]
    seen: set[str] = set()
    out: list[str] = []
    for pattern in base:
        if pattern not in seen:
            seen.add(pattern)
            out.append(pattern)
    return out


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


# --------------------------------------------------------------------------
# Stack detection — used by `proofloop init` for a transparent summary and to
# seed repo-local deploy entrypoints the built-in defaults might not cover.
# --------------------------------------------------------------------------

#: Marker file (or directory) → the deploy platform it indicates. Every one
#: of these platforms is already covered by DEFAULT_DEPLOY_PATTERNS; the
#: detection is for a transparent init summary, not for coverage.
_STACK_MARKERS: list[tuple[str, str]] = [
    ("vercel.json", "Vercel"),
    (".vercel", "Vercel"),
    ("netlify.toml", "Netlify"),
    ("fly.toml", "Fly.io"),
    ("railway.json", "Railway"),
    ("railway.toml", "Railway"),
    ("wrangler.toml", "Cloudflare (wrangler)"),
    ("wrangler.jsonc", "Cloudflare (wrangler)"),
    ("wrangler.json", "Cloudflare (wrangler)"),
    ("Procfile", "Heroku"),
    ("serverless.yml", "Serverless Framework"),
    ("serverless.yaml", "Serverless Framework"),
    ("sst.config.ts", "SST"),
    ("samconfig.toml", "AWS SAM"),
    ("cdk.json", "AWS CDK"),
    ("Pulumi.yaml", "Pulumi"),
    ("Pulumi.yml", "Pulumi"),
    ("Chart.yaml", "Kubernetes (Helm)"),
    ("kustomization.yaml", "Kubernetes (kustomize)"),
    ("k8s", "Kubernetes"),
    ("Dockerfile", "Docker"),
    ("app.yaml", "Google App Engine"),
    ("config/deploy.rb", "Capistrano/Kamal"),
]

#: package.json script names that look like a production deploy/release.
_DEPLOY_SCRIPT_RE = re.compile(r"(?:^|:)(?:deploy|release|ship|publish)(?::|$)", re.IGNORECASE)
_BARE_DEPLOY_NAMES = {"deploy", "release", "ship", "publish"}


def detect_deploy_stack(root: Path) -> list[str]:
    """Human labels for deploy platforms detected from marker files.

    Every detected platform is already covered by DEFAULT_DEPLOY_PATTERNS;
    this drives a transparent ``proofloop init`` summary. Terraform is matched
    by any top-level ``*.tf`` file.
    """
    found: list[str] = []
    for marker, label in _STACK_MARKERS:
        if (root / marker).exists() and label not in found:
            found.append(label)
    if any(root.glob("*.tf")) and "Terraform" not in found:
        found.append("Terraform")
    return found


def detect_extra_deploy_patterns(root: Path) -> list[str]:
    """Repo-local deploy entrypoints the built-in defaults might not cover.

    Seeded by ``proofloop init`` into ``deploy_patterns_extra``. Currently:
    ``package.json`` scripts named like ``deploy``/``release``/``ship``/
    ``publish`` — including colon-suffixed variants (``deploy:prod``). The
    bare names are already in the defaults, so only the suffixed ones are
    seeded here (each as a ``npm/pnpm/yarn/bun run <name>`` pattern).
    """
    pkg = root / "package.json"
    if not pkg.exists():
        return []
    try:
        data = json.loads(pkg.read_text(encoding="utf-8")) or {}
        scripts = data.get("scripts") or {}
    except (OSError, ValueError):
        return []
    extras: list[str] = []
    for name in scripts:
        if not isinstance(name, str) or name in _BARE_DEPLOY_NAMES:
            continue
        if _DEPLOY_SCRIPT_RE.search(name):
            pattern = _cmd(rf"(?:npm|pnpm|yarn|bun)\s+run\s+{re.escape(name)}\b")
            if pattern not in extras:
                extras.append(pattern)
    return extras


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

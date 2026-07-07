"""Setup discovery for Proofloop task/benchmark loops."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .session import now_iso

ADAPTER_VERSION = "2"
PROOFLOOP_AGENTS_MARKER = "<!-- proofloop-task-loop -->"
PROOFLOOP_AGENTS_END_MARKER = "<!-- /proofloop-task-loop -->"

NODE_UI_FRAMEWORKS = {
    "@vitejs/plugin-react": ("vite", "http://localhost:5173"),
    "vite": ("vite", "http://localhost:5173"),
    "next": ("next", "http://localhost:3000"),
    "react-scripts": ("create-react-app", "http://localhost:3000"),
    "@remix-run/dev": ("remix", "http://localhost:3000"),
    "astro": ("astro", "http://localhost:4321"),
    "svelte": ("svelte", "http://localhost:5173"),
}
NODE_API_FRAMEWORKS = {
    "@nestjs/core": "nestjs",
    "@trpc/server": "trpc",
    "express": "express",
    "fastify": "fastify",
    "hono": "hono",
    "koa": "koa",
}
PY_API_FRAMEWORKS = {
    "django": "django",
    "fastapi": "fastapi",
    "flask": "flask",
    "litestar": "litestar",
    "starlite": "starlite",
}


@dataclass
class ProjectSignals:
    package_manager: str | None = None
    setup_commands: list[list[str]] = field(default_factory=list)
    run_commands: list[list[str]] = field(default_factory=list)
    verify_commands: list[list[str]] = field(default_factory=list)
    required_live_markers: list[str] = field(default_factory=list)
    live_urls: list[str] = field(default_factory=list)
    api_endpoints: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    env_files: list[str] = field(default_factory=list)
    requires_live_ui: bool = False
    requires_live_api: bool = False
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "package_manager": self.package_manager,
            "setup_commands": self.setup_commands,
            "run_commands": self.run_commands,
            "verify_commands": self.verify_commands,
            "required_live_markers": self.required_live_markers,
            "live_urls": self.live_urls,
            "api_endpoints": self.api_endpoints,
            "frameworks": self.frameworks,
            "env_files": self.env_files,
            "requires_live_ui": self.requires_live_ui,
            "requires_live_api": self.requires_live_api,
            "files": self.files,
        }


@dataclass
class SetupResult:
    changed: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adapter_path: str | None = None
    signals: ProjectSignals = field(default_factory=ProjectSignals)

    def to_dict(self) -> dict:
        return {
            "changed": self.changed,
            "existing": self.existing,
            "warnings": self.warnings,
            "adapter_path": self.adapter_path,
            "signals": self.signals.to_dict(),
        }


def detect_project_signals(root: Path) -> ProjectSignals:
    root = Path(root)
    signals = ProjectSignals()

    package_json = root / "package.json"
    if package_json.is_file():
        signals.files.append("package.json")
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pkg = {}
        scripts = pkg.get("scripts") if isinstance(pkg, dict) else {}
        deps = {}
        if isinstance(pkg, dict):
            deps.update(pkg.get("dependencies") or {})
            deps.update(pkg.get("devDependencies") or {})
        pm = _node_package_manager(root)
        signals.package_manager = pm
        signals.setup_commands.append(_node_install_command(root, pm))
        if isinstance(scripts, dict):
            for name in ("dev", "start"):
                if name in scripts:
                    signals.run_commands.append([pm, "run", name])
                    break
            for name in (
                "test:e2e",
                "e2e",
                "test:ui",
                "playwright",
                "test:integration",
                "test",
            ):
                if name in scripts:
                    signals.verify_commands.append([pm, "run", name])
                    break
        _detect_node_stack(root, signals, scripts, deps)

    if (root / "pyproject.toml").is_file():
        signals.files.append("pyproject.toml")
        signals.setup_commands.append(_python_install_command(root))
        signals.verify_commands.append(_python_verify_command(root))
        _detect_python_stack(root, signals, _read_pyproject_dependencies(root))
    elif (root / "requirements.txt").is_file():
        signals.files.append("requirements.txt")
        signals.setup_commands.append(["python", "-m", "pip", "install", "-r", "requirements.txt"])
        signals.verify_commands.append(_python_verify_command(root))
        _detect_python_stack(root, signals, _read_requirements(root))

    for rel in (".env.example", ".env.sample", ".env.local.example", "example.env"):
        if (root / rel).is_file():
            signals.env_files.append(rel)
            signals.files.append(rel)

    for rel in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if (root / rel).is_file():
            signals.files.append(rel)
            signals.run_commands.append(["docker", "compose", "up", "-d"])
            signals.required_live_markers += ["status 200"]

    if (root / "convex.json").is_file() or (root / "convex").is_dir():
        signals.files.append("convex")
        if not any(cmd[:2] == ["npx", "convex"] for cmd in signals.setup_commands):
            signals.setup_commands.append(["npx", "convex", "dev", "--once"])
        signals.frameworks.append("convex")
        signals.requires_live_api = True
        signals.required_live_markers += ["convex", "api"]

    signals.api_endpoints += _detect_api_endpoints(root)
    if signals.api_endpoints:
        signals.requires_live_api = True
        if any(endpoint.startswith("/api") for endpoint in signals.api_endpoints):
            signals.required_live_markers.append("api")

    if not signals.required_live_markers:
        signals.required_live_markers = ["status 200"]
    if signals.requires_live_ui and "status 200" not in signals.required_live_markers:
        signals.required_live_markers.append("status 200")
    if signals.requires_live_api and "status 200" not in signals.required_live_markers:
        signals.required_live_markers.append("status 200")
    signals.required_live_markers = _dedupe(signals.required_live_markers)
    signals.live_urls = _dedupe(signals.live_urls)
    signals.api_endpoints = _dedupe(signals.api_endpoints)
    signals.frameworks = _dedupe(signals.frameworks)
    signals.env_files = _dedupe(signals.env_files)
    signals.files = _dedupe(signals.files)
    signals.setup_commands = _dedupe_commands(signals.setup_commands)
    signals.run_commands = _dedupe_commands(signals.run_commands)
    signals.verify_commands = _dedupe_commands(signals.verify_commands)
    return signals


def ensure_agents_guidance(root: Path) -> tuple[bool, str]:
    path = Path(root) / "AGENTS.md"
    section = _render_agents_guidance()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if PROOFLOOP_AGENTS_MARKER in text:
            updated = _replace_agents_guidance(text, section)
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                return True, "refreshed AGENTS.md Proofloop task-loop guidance"
            return False, "AGENTS.md already has Proofloop task-loop guidance"
        path.write_text(text.rstrip() + "\n\n" + section.lstrip(), encoding="utf-8")
        return True, "updated AGENTS.md with Proofloop task-loop guidance"
    path.write_text(section.lstrip(), encoding="utf-8")
    return True, "wrote AGENTS.md with Proofloop task-loop guidance"


def ensure_benchmark_adapter(
    root: Path,
    benchmark: str,
    signals: ProjectSignals | None = None,
    *,
    refresh: bool = False,
) -> tuple[bool, Path]:
    root = Path(root)
    signals = signals or detect_project_signals(root)
    adapter_dir = root / ".proofloop" / "benchmark-adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(benchmark)
    path = adapter_dir / f"{name}.json"
    existing = load_adapter(path) if path.is_file() else {}
    adapter = _merge_adapter(existing, benchmark, signals, refresh=refresh)
    if adapter == existing:
        return False, path
    path.write_text(json.dumps(adapter, indent=2) + "\n", encoding="utf-8")
    return True, path


def load_adapter(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _render_agents_guidance() -> str:
    return f"""
{PROOFLOOP_AGENTS_MARKER}
## Proofloop task loop

- Before benchmark work, run `proofloop task setup --benchmark <name>` if the adapter, hooks, or AGENTS guidance are missing or stale.
- For benchmark tasks, set up the local environment yourself instead of refusing because setup is local.
- Use the adapter's install/startup/verify command candidates, but adjust them to the repo if a command is stale.
- Run the task end to end through the live UI/API path. Do not stop at unit tests when the task requires browser or backend behavior.
- Do not complete benchmark tasks with mocks, stubs, hard-coded fixtures, deterministic demo paths, intercepted network responses, fake providers, canned screenshots, or fixture-only data unless the task explicitly asks for them.
- Collect success evidence matching the adapter schema: commands and exit codes, services started, live URLs/endpoints exercised, required markers, verifier output, browser/network traces or screenshots where relevant, and proof artifact paths.
- If Proofloop writes `.proofloop/task-runs/*/feedback.md`, follow that corrective instruction and rerun the live verifier.
{PROOFLOOP_AGENTS_END_MARKER}
"""


def _replace_agents_guidance(text: str, section: str) -> str:
    start = text.find(PROOFLOOP_AGENTS_MARKER)
    if start == -1:
        return text.rstrip() + "\n\n" + section.lstrip()

    end_marker = text.find(PROOFLOOP_AGENTS_END_MARKER, start)
    if end_marker != -1:
        end = end_marker + len(PROOFLOOP_AGENTS_END_MARKER)
        while end < len(text) and text[end] in " \t\r\n":
            end += 1
        return _splice_agents_guidance(text[:start], section, text[end:])

    lines = text.splitlines(keepends=True)
    cursor = 0
    start_line = 0
    for index, line in enumerate(lines):
        if cursor <= start < cursor + len(line):
            start_line = index
            break
        cursor += len(line)

    end_line = len(lines)
    seen_proofloop_heading = False
    for index in range(start_line + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("## "):
            if seen_proofloop_heading:
                end_line = index
                break
            seen_proofloop_heading = True

    return _splice_agents_guidance(
        "".join(lines[:start_line]),
        section,
        "".join(lines[end_line:]),
    )


def _splice_agents_guidance(before: str, section: str, after: str) -> str:
    before = before.rstrip()
    body = section.strip()
    after = after.lstrip()
    if before and after:
        return before + "\n\n" + body + "\n\n" + after
    if before:
        return before + "\n\n" + body + "\n"
    if after:
        return body + "\n\n" + after
    return body + "\n"


def _merge_adapter(
    existing: dict,
    benchmark: str,
    signals: ProjectSignals,
    *,
    refresh: bool,
) -> dict:
    if not isinstance(existing, dict):
        existing = {}
    desired = _render_adapter(
        benchmark,
        signals,
        created_at=str(existing.get("created_at") or now_iso()),
    )
    if not refresh:
        desired = _with_existing_command_defaults(desired, existing)
    if not existing:
        return desired

    merged = dict(existing)
    schema_stale = str(existing.get("schema_version") or "") != ADAPTER_VERSION
    command_keys = {
        "command_plan",
        "install_commands",
        "setup_commands",
        "startup_commands",
        "run_commands",
        "verify_commands",
        "required_live_markers",
    }
    for key, value in desired.items():
        if key == "created_at":
            merged[key] = str(existing.get("created_at") or value)
        elif refresh or key not in existing or _adapter_value_incomplete(existing.get(key)):
            merged[key] = value
        elif schema_stale and key not in command_keys:
            merged[key] = value

    if merged != existing:
        merged["updated_at"] = now_iso()
    return merged


def _with_existing_command_defaults(desired: dict, existing: dict) -> dict:
    desired = dict(desired)
    install = _existing_command_list(
        existing,
        "install_commands",
        "setup_commands",
        fallback=desired["install_commands"],
    )
    startup = _existing_command_list(
        existing,
        "startup_commands",
        "run_commands",
        fallback=desired["startup_commands"],
    )
    verify = _existing_command_list(
        existing,
        "verify_commands",
        fallback=desired["verify_commands"],
    )
    desired["install_commands"] = install
    desired["setup_commands"] = install
    desired["startup_commands"] = startup
    desired["run_commands"] = startup
    desired["verify_commands"] = verify
    desired["command_plan"] = {
        "install": install,
        "startup": startup,
        "verify": verify,
    }
    return desired


def _existing_command_list(
    existing: dict,
    *keys: str,
    fallback: list[list[str]],
) -> list[list[str]]:
    for key in keys:
        value = existing.get(key)
        if (
            isinstance(value, list)
            and value
            and all(isinstance(command, list) for command in value)
        ):
            return value
    return fallback


def _render_adapter(
    benchmark: str,
    signals: ProjectSignals,
    *,
    created_at: str,
) -> dict:
    command_plan = {
        "install": signals.setup_commands,
        "startup": signals.run_commands,
        "verify": signals.verify_commands,
    }
    return {
        "schema_version": ADAPTER_VERSION,
        "benchmark": benchmark,
        "created_at": created_at,
        "project_signals": signals.to_dict(),
        "command_plan": command_plan,
        "install_commands": signals.setup_commands,
        "setup_commands": signals.setup_commands,
        "startup_commands": signals.run_commands,
        "run_commands": signals.run_commands,
        "verify_commands": signals.verify_commands,
        "required_live_markers": signals.required_live_markers,
        "live_ui_api_requirements": _live_ui_api_requirements(signals),
        "meta_rubric": _live_browser_task_meta_rubric(signals),
        "mock_stub_rejection_signals": _mock_stub_rejection_signals(),
        "success_evidence_schema": _success_evidence_schema(),
        "codex_contract": _codex_contract(),
    }


def _live_ui_api_requirements(signals: ProjectSignals) -> dict:
    requires_live_ui = signals.requires_live_ui or bool(signals.live_urls)
    requires_live_api = signals.requires_live_api or bool(signals.api_endpoints)
    if not requires_live_ui and not requires_live_api:
        requires_live_ui = True
        requires_live_api = True
    return {
        "requires_live_ui": requires_live_ui,
        "requires_live_api": requires_live_api,
        "allowed_hosts": ["localhost", "127.0.0.1", "::1"],
        "candidate_live_urls": signals.live_urls,
        "candidate_api_endpoints": signals.api_endpoints,
        "env_files": signals.env_files,
        "required_markers": signals.required_live_markers,
        "proof_must_show": [
            "a live server or service was started or reused",
            "the task path exercised a real browser, HTTP request, or backend handler",
            "the verifier exited 0 after the final changes",
            "required live markers appeared in trusted verifier/proof output",
        ],
    }


def _live_browser_task_meta_rubric(signals: ProjectSignals) -> dict:
    """Contract for LLM-proposed judged fields in live UI benchmark tasks."""

    requirements = _live_ui_api_requirements(signals)
    return {
        "name": "live_browser_benchmark_task",
        "purpose": (
            "Let the agent propose context-specific judged fields for setup, "
            "execution, and proof quality while Proofloop validates the field "
            "shape before any score is computed."
        ),
        "llm_may_propose_fields": True,
        "proofloop_validates_fields": True,
        "context_sources": [
            {
                "id": "benchmark_task",
                "use": "task id, user goal, benchmark rules, and required success path",
            },
            {
                "id": "repo_adapter",
                "use": "install/startup/verify commands, live URLs, API endpoints, and markers",
            },
            {
                "id": "trusted_proof",
                "use": "verifier output, server logs, browser traces, network logs, screenshots, and recordings",
            },
            {
                "id": "agent_transcript",
                "use": "agent decisions and setup attempts; never sufficient alone for live success",
            },
        ],
        "field_contract": {
            "field_id": "required stable snake_case id",
            "definition": "must be concrete, observable, and answerable from supplied evidence",
            "question": "single yes/no question the judge can answer",
            "polarity": "one of: positive, negative, veto",
            "evidence_sources": "non-empty list of accepted source ids",
            "weight_class": "one of: low, medium, high, veto",
            "failure_code": "issue code to emit when a required/veto field fails",
        },
        "reject_field_if": [
            "field_id is not stable snake_case",
            "definition is vague, subjective, or overlaps another accepted field",
            "field can be answered only from the assistant's own success claim",
            "field gives the model a custom numeric weight or formula",
            "field does not relate to local setup, live UI/API execution, verifier success, or proof quality",
        ],
        "required_seed_fields": _live_browser_seed_fields(requirements),
        "scoring_policy": {
            "formula_owner": "Proofloop",
            "model_output": "booleans plus cited evidence only",
            "score_inputs": "validated positive, negative, and veto booleans",
            "veto_behavior": "any true veto field blocks task success regardless of positives",
            "assistant_claims": "assistant-only claims can explain intent but cannot satisfy live evidence fields",
        },
    }


def _live_browser_seed_fields(requirements: dict) -> list[dict]:
    fields = [
        {
            "field_id": "local_environment_prepared",
            "definition": "Dependencies, local configuration, and required services were installed or explicitly verified.",
            "question": "Did the run prepare the local project instead of refusing setup?",
            "polarity": "positive",
            "evidence_sources": ["agent_transcript", "trusted_proof"],
            "weight_class": "medium",
            "failure_code": "local_setup_refusal",
        },
        {
            "field_id": "live_services_started",
            "definition": "The app server, API server, database, or other required services were started or reused locally.",
            "question": "Does trusted evidence show a live service was available for the task?",
            "polarity": "positive",
            "evidence_sources": ["repo_adapter", "trusted_proof"],
            "weight_class": "high",
            "failure_code": "missing_live_evidence",
        },
        {
            "field_id": "browser_ui_exercised",
            "definition": "The task path was exercised through a real browser UI, not only unit tests or assistant narration.",
            "question": "Does proof show browser execution against the live UI?",
            "polarity": "positive",
            "evidence_sources": ["trusted_proof"],
            "weight_class": "high",
            "failure_code": "missing_live_evidence",
        },
        {
            "field_id": "live_api_observed",
            "definition": "The run observed real HTTP/API/backend traffic relevant to the task.",
            "question": "Does trusted proof include real endpoint, request, response, or status evidence?",
            "polarity": "positive",
            "evidence_sources": ["repo_adapter", "trusted_proof"],
            "weight_class": "high",
            "failure_code": "missing_live_evidence",
        },
        {
            "field_id": "required_markers_observed",
            "definition": "Every required marker from the adapter or CLI appeared in trusted verifier/proof output.",
            "question": "Were all required live markers observed outside assistant-only claims?",
            "polarity": "positive",
            "evidence_sources": ["repo_adapter", "trusted_proof"],
            "weight_class": "high",
            "failure_code": "required_live_marker_missing",
        },
        {
            "field_id": "final_verifier_passed",
            "definition": "The final verifier command completed successfully after the task run.",
            "question": "Did the final verifier exit 0?",
            "polarity": "positive",
            "evidence_sources": ["trusted_proof"],
            "weight_class": "high",
            "failure_code": "verification_failed",
        },
        {
            "field_id": "mock_stub_success_path_used",
            "definition": "The claimed success depended on mocks, stubs, fake providers, canned screenshots, intercepted network, or deterministic demo paths.",
            "question": "Did the success path rely on non-live substitutes?",
            "polarity": "veto",
            "evidence_sources": ["agent_transcript", "trusted_proof"],
            "weight_class": "veto",
            "failure_code": "mock_or_stub_completion",
        },
        {
            "field_id": "assistant_claim_only",
            "definition": "The only live UI/API evidence is the assistant's own statement, with no verifier or proof artifact support.",
            "question": "Is live success supported only by assistant narration?",
            "polarity": "veto",
            "evidence_sources": ["agent_transcript"],
            "weight_class": "veto",
            "failure_code": "missing_live_evidence",
        },
    ]
    if requirements.get("requires_live_ui") is False:
        fields = [field for field in fields if field["field_id"] != "browser_ui_exercised"]
    if requirements.get("requires_live_api") is False:
        fields = [field for field in fields if field["field_id"] != "live_api_observed"]
    return fields


def _mock_stub_rejection_signals() -> list[dict]:
    return [
        {
            "code": "mock_or_stub_completion",
            "patterns": [
                r"\bmock(?:ed|ing)?\b",
                r"\bstub(?:bed|bing)?\b",
                r"\bfake\b",
                r"\bfixture-only\b",
                r"\bcanned\b",
                r"\bhard-coded\b",
                r"\bdeterministic demo path\b",
                r"\bMSW\b|\bnock\b|\bintercepted network\b",
            ],
            "action": (
                "Reject success unless the user task explicitly requires a mock "
                "or the mock is only an internal test dependency outside the claimed "
                "live UI/API evidence."
            ),
        }
    ]


def _success_evidence_schema() -> dict:
    return {
        "type": "object",
        "required": [
            "task_id",
            "changed_paths",
            "commands",
            "services",
            "live_ui_api",
            "verifier",
            "proof_artifacts",
            "mock_stub_review",
        ],
        "properties": {
            "task_id": "Benchmark/task identifier or user task summary.",
            "changed_paths": "Files changed for the task, excluding generated proof logs.",
            "commands": "Install, startup, migration/seed, and verifier commands with exit codes.",
            "services": "Live services started or reused, with ports/URLs when known.",
            "live_ui_api": "Browser/API actions, endpoints, status codes, and required markers observed.",
            "verifier": "Final verifier command, exit code, and log path.",
            "proof_artifacts": "Transcript, server logs, browser/network traces, screenshots, or recordings.",
            "mock_stub_review": "Statement that success did not rely on mocks/stubs/fake providers unless explicitly required.",
        },
    }


def _codex_contract() -> list[str]:
    return [
        "Inspect this adapter before starting and treat command_plan entries as candidates, not excuses to stop.",
        "Install dependencies and create local-only configuration needed for the task.",
        "Start or reuse real UI/API services required by the app.",
        "Run the benchmark task end to end through the live UI/API path, including browser/API evidence when applicable.",
        "Do not claim success through mocks, stubs, hard-coded fixtures, fake providers, intercepted network responses, canned screenshots, or deterministic demo paths unless the task explicitly asks for them.",
        "Run the final verifier and collect trusted output containing every required live marker.",
        "Finish with changed paths, commands and exit codes, live URLs/endpoints exercised, verifier log, and proof artifact paths.",
    ]


def _adapter_value_incomplete(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _node_install_command(root: Path, package_manager: str) -> list[str]:
    if package_manager == "npm" and (root / "package-lock.json").is_file():
        return ["npm", "ci"]
    if package_manager == "pnpm" and (root / "pnpm-lock.yaml").is_file():
        return ["pnpm", "install", "--frozen-lockfile"]
    if package_manager == "yarn" and (root / "yarn.lock").is_file():
        return ["yarn", "install", "--frozen-lockfile"]
    if package_manager == "bun" and (
        (root / "bun.lockb").is_file() or (root / "bun.lock").is_file()
    ):
        return ["bun", "install", "--frozen-lockfile"]
    return [package_manager, "install"]


def _python_install_command(root: Path) -> list[str]:
    if (root / "uv.lock").is_file():
        return ["uv", "sync"]
    if (root / "poetry.lock").is_file():
        return ["poetry", "install"]
    if (root / "pdm.lock").is_file():
        return ["pdm", "install"]
    return ["python", "-m", "pip", "install", "-e", "."]


def _python_verify_command(root: Path) -> list[str]:
    if (root / "uv.lock").is_file():
        return ["uv", "run", "pytest", "-q"]
    if (root / "poetry.lock").is_file():
        return ["poetry", "run", "pytest", "-q"]
    if (root / "pdm.lock").is_file():
        return ["pdm", "run", "pytest", "-q"]
    return ["python", "-m", "pytest", "-q"]


def _detect_node_stack(
    root: Path,
    signals: ProjectSignals,
    scripts: object,
    deps: dict,
) -> None:
    dep_names = {str(name).lower() for name in deps}
    script_values = []
    if isinstance(scripts, dict):
        script_values = [str(value).lower() for value in scripts.values()]
    script_text = "\n".join(script_values)

    for rel in (
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "playwright.config.ts",
        "playwright.config.js",
        "playwright.config.mjs",
    ):
        if (root / rel).is_file():
            signals.files.append(rel)

    for dependency, (framework, url) in NODE_UI_FRAMEWORKS.items():
        if dependency in dep_names or framework in script_text:
            signals.frameworks.append(framework)
            signals.live_urls.append(url)
            signals.requires_live_ui = True

    for dependency, framework in NODE_API_FRAMEWORKS.items():
        if dependency in dep_names or framework in script_text:
            signals.frameworks.append(framework)
            signals.requires_live_api = True

    if _has_next_api_routes(root):
        signals.frameworks.append("next-api")
        signals.requires_live_api = True

    has_playwright = (
        "playwright" in dep_names
        or "@playwright/test" in dep_names
        or any(
            (root / rel).is_file()
            for rel in (
                "playwright.config.ts",
                "playwright.config.js",
                "playwright.config.mjs",
            )
        )
    )
    if has_playwright:
        signals.frameworks.append("playwright")
        signals.requires_live_ui = True
        signals.required_live_markers += ["browser", "status 200"]
        if not signals.verify_commands:
            signals.verify_commands.append(["npx", "playwright", "test"])


def _detect_python_stack(root: Path, signals: ProjectSignals, deps: list[str]) -> None:
    lower_deps = {_dependency_name(dep) for dep in deps}
    for dependency, framework in PY_API_FRAMEWORKS.items():
        if dependency in lower_deps:
            signals.frameworks.append(framework)
            signals.requires_live_api = True

    if (root / "manage.py").is_file():
        signals.frameworks.append("django")
        signals.requires_live_api = True
        signals.run_commands.append(["python", "manage.py", "runserver"])
    elif "fastapi" in lower_deps or "uvicorn" in lower_deps:
        command = _uvicorn_command(root)
        if command:
            signals.run_commands.append(command)
    elif "flask" in lower_deps and (root / "app.py").is_file():
        signals.run_commands.append(["python", "-m", "flask", "--app", "app", "run"])
    elif signals.requires_live_api and (root / "app.py").is_file():
        signals.run_commands.append(["python", "app.py"])


def _read_pyproject_dependencies(root: Path) -> list[str]:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    deps: list[str] = []
    project = data.get("project")
    if isinstance(project, dict):
        deps.extend(_dependency_names(project.get("dependencies")))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for values in optional.values():
                deps.extend(_dependency_names(values))

    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        poetry_deps = poetry.get("dependencies")
        if isinstance(poetry_deps, dict):
            deps.extend(str(name) for name in poetry_deps if name.lower() != "python")
    return _dedupe(deps)


def _read_requirements(root: Path) -> list[str]:
    try:
        lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    deps: list[str] = []
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://")):
            continue
        deps.append(_dependency_name(line))
    return _dedupe([dep for dep in deps if dep])


def _dependency_names(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    names: list[str] = []
    for value in values:
        if isinstance(value, str):
            names.append(_dependency_name(value))
    return [name for name in names if name]


def _dependency_name(requirement: str) -> str:
    head = re.split(r"[\[<>=~!;\s]", requirement.strip(), maxsplit=1)[0]
    return head.lower().replace("_", "-")


def _uvicorn_command(root: Path) -> list[str] | None:
    for module in ("app", "main", "server"):
        path = root / f"{module}.py"
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "FastAPI(" in text or "fastapi" in text.lower():
            return ["python", "-m", "uvicorn", f"{module}:app", "--reload"]
    return None


def _has_next_api_routes(root: Path) -> bool:
    return (root / "pages" / "api").is_dir() or (root / "app" / "api").is_dir()


def _detect_api_endpoints(root: Path) -> list[str]:
    endpoints: list[str] = []
    for path in _iter_candidate_api_files(root):
        endpoints += _endpoints_from_path(root, path)
        if path.suffix == ".py":
            endpoints += _python_route_endpoints(path)
    return _dedupe(endpoints)[:40]


def _iter_candidate_api_files(root: Path) -> list[Path]:
    skipped = {
        ".git",
        ".proofloop",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".next",
        "__pycache__",
    }
    out: list[Path] = []
    for path in root.rglob("*"):
        if len(out) >= 80:
            break
        if not path.is_file() or path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".py"}:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skipped for part in rel_parts):
            continue
        try:
            if path.stat().st_size > 256_000:
                continue
        except OSError:
            continue
        if "api" in rel_parts or path.name in {"app.py", "main.py", "server.py", "routes.py"}:
            out.append(path)
    return out


def _endpoints_from_path(root: Path, path: Path) -> list[str]:
    rel = path.relative_to(root)
    parts = rel.parts
    endpoints: list[str] = []
    if "api" in parts and parts[0] in {"app", "src"}:
        api_index = parts.index("api")
        suffix = list(parts[api_index + 1 :])
        if suffix and Path(suffix[-1]).stem in {"route", "index"}:
            suffix = suffix[:-1]
        endpoint = "/api/" + "/".join(_route_segment(part) for part in suffix)
        endpoints.append(endpoint.rstrip("/") or "/api")
    if len(parts) >= 3 and parts[0] == "pages" and parts[1] == "api":
        suffix = list(parts[2:])
        suffix[-1] = Path(suffix[-1]).stem
        if suffix[-1] == "index":
            suffix = suffix[:-1]
        endpoint = "/api/" + "/".join(_route_segment(part) for part in suffix)
        endpoints.append(endpoint.rstrip("/") or "/api")
    return endpoints


def _route_segment(segment: str) -> str:
    stem = Path(segment).stem if "." in segment else segment
    if stem.startswith("[") and stem.endswith("]"):
        return ":" + stem.strip("[]").strip(".")
    return stem


def _python_route_endpoints(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    pattern = re.compile(
        r"@\s*(?:\w+\.)?(?:app|router|bp)\."
        r"(?:get|post|put|patch|delete|route)\(\s*['\"]([^'\"]+)",
        flags=re.IGNORECASE,
    )
    return [match.group(1) for match in pattern.finditer(text)]


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "bun.lockb").is_file() or (root / "bun.lock").is_file():
        return "bun"
    return "npm"


def _safe_name(name: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in name.strip())
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "benchmark"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _dedupe_commands(commands: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        key = tuple(command)
        if key not in seen:
            seen.add(key)
            out.append(command)
    return out

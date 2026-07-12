import os
import subprocess
from pathlib import Path

import pytest

from proofjury.checks.base import CheckContext
from proofjury.context import iter_source_files, load_config
from proofjury.memory.schema import MemoryRecord
from proofjury.session import load_session, worktree_digest


class Repo:
    """Thin helper around a temp repo root."""

    def __init__(self, root: Path):
        self.root = root

    def write(self, rel: str, content: str, executable: bool = False) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if executable:
            path.chmod(0o755)
        return path

    def write_bytes(self, rel: str, content: bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def git(self, *args: str) -> str:
        cp = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=True
        )
        return cp.stdout


@pytest.fixture(autouse=True)
def _offline_judge(monkeypatch, tmp_path):
    """Tests that go through os.environ (CLI paths) must never hit a real LLM.

    Also isolates the user-level judge config from the developer's real
    ~/.config so tests never read a real key and are reproducible anywhere.
    """
    monkeypatch.setenv("PROOFJURY_NO_LLM", "1")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for var in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "PROOFJURY_JUDGE_PROVIDER",
        "PROOFJURY_JUDGE_MODEL",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Repo:
    """A temp dir initialized as a git repo (identity configured)."""
    repo = Repo(tmp_path)
    repo.git("init", "-q")
    repo.git("config", "user.email", "test@proofjury.local")
    repo.git("config", "user.name", "proofjury-tests")
    return repo


@pytest.fixture
def scrubbed_env(tmp_path_factory) -> dict[str, str]:
    """Minimal deploy environment so host env vars never leak into checks.

    HOME must be per-test AND outside the test repo: the gate registers
    its store in a user-level registry under HOME, so a shared HOME would
    let tests recall each other's stores cross-repo, and a HOME inside
    the repo root would enter the worktree digest and re-arm tests_not_run.
    """
    home = tmp_path_factory.mktemp("proofjury-home")
    return {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin")}


@pytest.fixture
def make_ctx(scrubbed_env):
    """Build a CheckContext for a repo root, recomputing files + digest."""

    def _make(
        root: Path,
        env: dict | None = None,
        config: dict | None = None,
        session: dict | None = None,
    ) -> CheckContext:
        return CheckContext(
            root=root,
            env=dict(scrubbed_env) if env is None else env,
            config=load_config(root) if config is None else config,
            files=iter_source_files(root),
            session=load_session(root) if session is None else session,
            digest=worktree_digest(root),
        )

    return _make


@pytest.fixture
def record_factory():
    def _make(
        record_id: str = "chk_001",
        repo_id: str = "demo-repo",
        created_at: str = "2026-07-01T00:00:00Z",
        gate_passed: bool = False,
        checks: list | None = None,
        **overrides,
    ) -> MemoryRecord:
        if checks is None:
            checks = [
                {
                    "name": "env_vars",
                    "type": "deterministic",
                    "passed": False,
                    "failure_class": "missing_env_var",
                    "evidence": "STRIPE_API_KEY (payments.py:14) unset",
                }
            ]
        base = dict(
            id=record_id,
            repo_id=repo_id,
            created_at=created_at,
            action_intercepted="deploy",
            agent_source="unknown",
            context_ref=f".proofjury/runs/{record_id}/",
            checks=checks,
            gate_passed=gate_passed,
            diagnosis="diagnosis text",
            judge_input="judge input text",
            judge_output='{"diagnosis": "d", "fix_steps": []}',
            proof_refs=["checks.json"],
            recalled_from=None,
            judge_model_id="deterministic/proofjury-v1",
            resolution=None,
        )
        base.update(overrides)
        return MemoryRecord(**base)

    return _make

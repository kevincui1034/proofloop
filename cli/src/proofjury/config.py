"""User-level judge config store — one BYOK key across all projects.

A user has one judge key, not one per repo, so the key lives at
``${XDG_CONFIG_HOME:-~/.config}/proofjury/config.toml`` (0600, outside any
repo). Storing it per-repo would recreate exactly the hand-editing friction
the ``proofjury login`` flow removes.

Reading uses stdlib ``tomllib`` (py3.11+); writing hand-renders a minimal
``[judge]`` table so no third-party TOML writer is needed — the runtime
deps stay at typer + rich + httpx.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Mapping

#: provider -> the env var that carries its key.
PROVIDER_ENV_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

#: Auto-detect order when no provider is named explicitly.
_AUTODETECT_ORDER = ("openrouter", "anthropic", "openai")


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def config_path(env: Mapping[str, str] | None = None) -> Path:
    env = _env(env)
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        home = env.get("HOME")
        base = (Path(home) if home else Path.home()) / ".config"
    return base / "proofjury" / "config.toml"


def load_config(env: Mapping[str, str] | None = None) -> dict:
    """Parse the config file; ``{}`` when it's missing or malformed."""
    path = config_path(env)
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _toml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    # escape backslash first, then the quote
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _render_toml(data: Mapping) -> str:
    """Minimal TOML: bare top-level scalars, then ``[table]`` sections."""
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, Mapping):
            lines.append(f"{key} = {_toml_scalar(value)}")
    for key, value in data.items():
        if isinstance(value, Mapping):
            lines.append(f"[{key}]")
            for subkey, subval in value.items():
                if subval is None:
                    continue
                lines.append(f"{subkey} = {_toml_scalar(subval)}")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_judge_config(
    provider: str,
    api_key: str,
    model: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Write the ``[judge]`` table (0600), preserving any other tables."""
    config = load_config(env)
    judge: dict = {"provider": provider, "api_key": api_key}
    if model:
        judge["model"] = model
    config["judge"] = judge
    path = config_path(env)
    _atomic_write(path, _render_toml(config))
    os.chmod(path, 0o600)
    return path


def clear_judge_config(env: Mapping[str, str] | None = None) -> str | None:
    """Remove the ``[judge]`` table; delete the file if that's all it held.

    Returns the removed provider (for the CLI to report), or None.
    """
    path = config_path(env)
    config = load_config(env)
    removed = config.get("judge")
    if removed is None:
        return None
    others = {k: v for k, v in config.items() if k != "judge"}
    if others:
        _atomic_write(path, _render_toml(others))
        os.chmod(path, 0o600)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return removed.get("provider") if isinstance(removed, dict) else None


def resolve_judge(
    env: Mapping[str, str] | None = None, config: dict | None = None
) -> dict | None:
    """Resolve ``{provider, api_key, model}`` or None.

    Precedence: PROOFJURY_NO_LLM → None; explicit provider (env
    PROOFJURY_JUDGE_PROVIDER or config ``[judge].provider``, key from the
    matching env var else the stored key); else auto-detect by env key
    presence (openrouter → anthropic → openai); else the stored config;
    else None. Model: PROOFJURY_JUDGE_MODEL → config ``[judge].model`` →
    None (adapter default).
    """
    env = _env(env)
    if env.get("PROOFJURY_NO_LLM"):
        return None
    if config is None:
        config = load_config(env)
    judge_cfg = config.get("judge") or {}
    model = env.get("PROOFJURY_JUDGE_MODEL") or judge_cfg.get("model") or None

    provider = env.get("PROOFJURY_JUDGE_PROVIDER") or judge_cfg.get("provider")
    if provider:
        provider = str(provider).strip().lower()
        env_key = PROVIDER_ENV_KEYS.get(provider)
        api_key = (env.get(env_key) if env_key else None) or judge_cfg.get("api_key")
        if api_key:
            return {"provider": provider, "api_key": api_key, "model": model}
        return None

    for prov in _AUTODETECT_ORDER:
        key = env.get(PROVIDER_ENV_KEYS[prov])
        if key:
            return {"provider": prov, "api_key": key, "model": model}

    stored_provider = judge_cfg.get("provider")
    stored_key = judge_cfg.get("api_key")
    if stored_provider and stored_key:
        return {
            "provider": str(stored_provider).strip().lower(),
            "api_key": stored_key,
            "model": model,
        }
    return None


def llm_configured(env: Mapping[str, str] | None = None) -> bool:
    """True iff an LLM judge would be selected (discoverability hint)."""
    return resolve_judge(env) is not None


#: Defaults for the repo-level ``.proofjury.toml [advisory]`` table. The
#: advisory judge is best-effort and never blocks, so it defaults ON —
#: it only actually runs when an LLM is configured (BYOK) anyway.
ADVISORY_DEFAULTS = {
    "enabled": True,
    "auto_inject_min_confidence": 0.7,  # ≥ → injected to the agent
    "hold_min_confidence": 0.4,         # ≥ → held for human approval
    "max_findings": 5,
    "diff_min_lines": 1,                # diff smaller than this → skip
    "tiers": [4, 5],                    # mute a whole tier with e.g. [4]
    "model": None,                      # None → the judge's resolved model
}


#: Defaults for the repo-level ``.proofjury.toml [memory]`` table. Cross-repo
#: recall reads other local repos' already-scrubbed stores read-only and
#: never affects pass/fail, so it defaults ON.
MEMORY_DEFAULTS = {
    "cross_repo": True,
}


def memory_settings(repo_config: dict | None) -> dict:
    """The ``[memory]`` table from ``.proofjury.toml`` merged over
    ``MEMORY_DEFAULTS``. Malformed values fall back to the default for
    that key — a config typo must never crash the gate.
    """
    settings = dict(MEMORY_DEFAULTS)
    table = (repo_config or {}).get("memory")
    if not isinstance(table, dict):
        return settings
    if isinstance(table.get("cross_repo"), bool):
        settings["cross_repo"] = table["cross_repo"]
    return settings


def cross_repo_enabled(
    repo_config: dict | None, env: Mapping[str, str] | None = None
) -> bool:
    """Whether this gate run participates in cross-repo memory recall.

    ``PROOFJURY_NO_CROSS_REPO`` (any non-empty value) wins over config —
    a belt-and-braces off switch for CI and scripted runs.
    """
    if _env(env).get("PROOFJURY_NO_CROSS_REPO"):
        return False
    return memory_settings(repo_config)["cross_repo"]


def advisory_settings(repo_config: dict | None) -> dict:
    """The ``[advisory]`` table from ``.proofjury.toml`` merged over
    ``ADVISORY_DEFAULTS``. Malformed values fall back to the default for
    that key — a config typo must never crash the gate.
    """
    settings = dict(ADVISORY_DEFAULTS)
    table = (repo_config or {}).get("advisory")
    if not isinstance(table, dict):
        return settings
    if isinstance(table.get("enabled"), bool):
        settings["enabled"] = table["enabled"]
    for key in ("auto_inject_min_confidence", "hold_min_confidence"):
        value = table.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            settings[key] = min(1.0, max(0.0, float(value)))
    for key in ("max_findings", "diff_min_lines"):
        value = table.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            settings[key] = value
    tiers = table.get("tiers")
    if isinstance(tiers, list):
        valid = [t for t in tiers if isinstance(t, int) and t in (4, 5)]
        settings["tiers"] = valid
    model = table.get("model")
    if isinstance(model, str) and model.strip():
        settings["model"] = model.strip()
    return settings

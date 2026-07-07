"""User-level judge config store: save/load, 0600 mode, resolve precedence."""

import stat

from proofloop import config


def _env(tmp_path, **extra):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    env.update(extra)
    return env


# -- save / load ------------------------------------------------------------


def test_save_load_roundtrip(tmp_path):
    env = _env(tmp_path)
    path = config.save_judge_config(
        "anthropic", "sk-ant-123", model="claude-haiku-4-5", env=env
    )
    assert path == config.config_path(env)
    assert path.exists()
    assert config.load_config(env)["judge"] == {
        "provider": "anthropic",
        "api_key": "sk-ant-123",
        "model": "claude-haiku-4-5",
    }


def test_save_without_model_omits_key(tmp_path):
    env = _env(tmp_path)
    config.save_judge_config("openai", "sk-openai", env=env)
    judge = config.load_config(env)["judge"]
    assert judge == {"provider": "openai", "api_key": "sk-openai"}
    assert "model" not in judge


def test_file_mode_is_0600(tmp_path):
    path = config.save_judge_config("openrouter", "k", env=_env(tmp_path))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_escapes_quotes_and_backslashes(tmp_path):
    env = _env(tmp_path)
    nasty = 'ab"cd\\ef'  # a quote and a backslash
    config.save_judge_config("openai", nasty, env=env)
    assert config.load_config(env)["judge"]["api_key"] == nasty


def test_load_missing_returns_empty(tmp_path):
    assert config.load_config(_env(tmp_path)) == {}


def test_load_malformed_returns_empty(tmp_path):
    env = _env(tmp_path)
    path = config.config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("this is := not valid toml [[[")
    assert config.load_config(env) == {}


# -- paths ------------------------------------------------------------------


def test_xdg_path_honored(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    assert config.config_path(env) == tmp_path / "xdg" / "proofloop" / "config.toml"


def test_home_path_when_no_xdg(tmp_path):
    env = {"HOME": str(tmp_path / "home")}
    assert (
        config.config_path(env)
        == tmp_path / "home" / ".config" / "proofloop" / "config.toml"
    )


# -- clear ------------------------------------------------------------------


def test_clear_deletes_file_when_only_judge(tmp_path):
    env = _env(tmp_path)
    path = config.save_judge_config("anthropic", "k", env=env)
    assert config.clear_judge_config(env) == "anthropic"
    assert not path.exists()


def test_clear_preserves_other_tables(tmp_path):
    env = _env(tmp_path)
    path = config.config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[other]\nkeep = "yes"\n\n[judge]\nprovider = "openai"\napi_key = "k"\n')
    assert config.clear_judge_config(env) == "openai"
    left = config.load_config(env)
    assert "judge" not in left
    assert left["other"] == {"keep": "yes"}


def test_clear_nothing_returns_none(tmp_path):
    assert config.clear_judge_config(_env(tmp_path)) is None


# -- resolve_judge precedence ----------------------------------------------


def test_resolve_no_llm_returns_none(tmp_path):
    env = _env(tmp_path, PROOFLOOP_NO_LLM="1", OPENROUTER_API_KEY="k")
    assert config.resolve_judge(env) is None


def test_resolve_autodetect_order_openrouter_first(tmp_path):
    env = _env(tmp_path, OPENROUTER_API_KEY="or", ANTHROPIC_API_KEY="an", OPENAI_API_KEY="oa")
    assert config.resolve_judge(env) == {
        "provider": "openrouter",
        "api_key": "or",
        "model": None,
    }


def test_resolve_autodetect_anthropic_over_openai(tmp_path):
    env = _env(tmp_path, ANTHROPIC_API_KEY="an", OPENAI_API_KEY="oa")
    assert config.resolve_judge(env)["provider"] == "anthropic"


def test_resolve_explicit_provider_env_overrides_order(tmp_path):
    env = _env(
        tmp_path,
        PROOFLOOP_JUDGE_PROVIDER="anthropic",
        OPENROUTER_API_KEY="or",
        ANTHROPIC_API_KEY="an",
    )
    assert config.resolve_judge(env) == {
        "provider": "anthropic",
        "api_key": "an",
        "model": None,
    }


def test_resolve_env_key_beats_stored_key(tmp_path):
    env = _env(tmp_path, OPENROUTER_API_KEY="env-key")
    config.save_judge_config("openrouter", "file-key", env=env)
    assert config.resolve_judge(env)["api_key"] == "env-key"


def test_resolve_stored_config_only(tmp_path):
    env = _env(tmp_path)
    config.save_judge_config("anthropic", "stored-key", model="claude-opus-4-8", env=env)
    assert config.resolve_judge(env) == {
        "provider": "anthropic",
        "api_key": "stored-key",
        "model": "claude-opus-4-8",
    }


def test_resolve_explicit_provider_with_stored_key(tmp_path):
    env = _env(tmp_path, PROOFLOOP_JUDGE_PROVIDER="anthropic")
    config.save_judge_config("anthropic", "stored", env=env)
    assert config.resolve_judge(env) == {
        "provider": "anthropic",
        "api_key": "stored",
        "model": None,
    }


def test_resolve_model_env_beats_config(tmp_path):
    env = _env(tmp_path, OPENROUTER_API_KEY="k", PROOFLOOP_JUDGE_MODEL="env/model")
    config.save_judge_config("openrouter", "x", model="file/model", env=env)
    assert config.resolve_judge(env)["model"] == "env/model"


def test_resolve_none_when_nothing(tmp_path):
    assert config.resolve_judge(_env(tmp_path)) is None


def test_llm_configured(tmp_path):
    env = _env(tmp_path)
    assert config.llm_configured(env) is False
    config.save_judge_config("openai", "k", env=env)
    assert config.llm_configured(env) is True
    assert config.llm_configured(_env(tmp_path, PROOFLOOP_NO_LLM="1")) is False

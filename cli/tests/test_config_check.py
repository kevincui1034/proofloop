"""config_mismatch: localhost, debug flags, test keys, ports, env hygiene."""

from proofloop.checks.config import check_config


def _details(result):
    return [e.detail for e in result.evidence]


def test_localhost_url_flagged_with_line(tmp_repo, make_ctx):
    tmp_repo.write(
        "config.py",
        '"""Cfg."""\n\nAPI_BASE_URL = "http://localhost:8000"\n',
    )
    result = check_config(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "config_mismatch"
    assert result.evidence[0].file == "config.py"
    assert result.evidence[0].line == 3
    assert "API_BASE_URL points at localhost" in result.evidence[0].detail


def test_debug_true_flagged_python_and_yaml(tmp_repo, make_ctx):
    tmp_repo.write("settings.py", "DEBUG = True\n")
    tmp_repo.write("app.yaml", "debug: true\n")
    result = check_config(make_ctx(tmp_repo.root))
    files = {e.file for e in result.evidence}
    assert files == {"settings.py", "app.yaml"}
    assert all("debug mode is enabled" in d for d in _details(result))


def test_sk_test_key_flagged(tmp_repo, make_ctx):
    tmp_repo.write("config.py", 'STRIPE_KEY = "sk_test_abc123"\n')
    result = check_config(make_ctx(tmp_repo.root))
    assert any("test-mode key" in d for d in _details(result))


def test_dev_port_in_url_setting_flagged(tmp_repo, make_ctx):
    tmp_repo.write(".env", "API_URL=https://app.example.com:3000\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert any("dev port :3000" in d for d in _details(result))


def test_next_public_secret_name_flagged(tmp_repo, make_ctx):
    tmp_repo.write(".env", "NEXT_PUBLIC_API_KEY=abc\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert any("NEXT_PUBLIC_API_KEY" in d and "secret" in d for d in _details(result))


def test_env_local_not_gitignored_flagged(tmp_repo, make_ctx):
    tmp_repo.write(".env.local", "FLAG=1\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert any(".env.local exists but is not gitignored" in d for d in _details(result))


def test_env_local_gitignored_ok(tmp_repo, make_ctx):
    tmp_repo.write(".env.local", "FLAG=1\n")
    tmp_repo.write(".gitignore", ".env.local\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_env_local_covered_by_glob(tmp_repo, make_ctx):
    tmp_repo.write(".env.local", "FLAG=1\n")
    tmp_repo.write(".gitignore", ".env*\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_non_config_files_not_scanned(tmp_repo, make_ctx):
    tmp_repo.write("main.py", 'URL = "http://localhost:8000"\n')
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_comments_ignored(tmp_repo, make_ctx):
    tmp_repo.write("config.py", '# API_BASE_URL = "http://localhost:8000"\n')
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_production_shaped_config_passes(tmp_repo, make_ctx):
    tmp_repo.write(
        "config.py",
        'API_BASE_URL = "https://api.example.com"\nDEBUG = False\n',
    )
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_json_quoted_keys_flagged(tmp_repo, make_ctx):
    tmp_repo.write(
        "appsettings.json",
        '{\n  "debug": true,\n  "api_host": "localhost:8000"\n}\n',
    )
    result = check_config(make_ctx(tmp_repo.root))
    assert not result.passed
    by_line = {e.line: e.detail for e in result.evidence}
    assert by_line[2] == "debug mode is enabled"
    assert by_line[3] == "api_host points at localhost"


def test_json_dev_port_flagged(tmp_repo, make_ctx):
    tmp_repo.write("deploy.json", '{"api_url": "https://app.example.com:3000"}\n')
    result = check_config(make_ctx(tmp_repo.root))
    assert any("dev port :3000" in d for d in _details(result))


def test_inline_comment_tail_ignored(tmp_repo, make_ctx):
    tmp_repo.write(
        "config.py",
        'API = "https://api.example.com"  # was http://localhost:8000\n',
    )
    tmp_repo.write(
        "app.yaml",
        "api_url: https://prod.example.com # debug: true on localhost\n",
    )
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_unquoted_url_survives_comment_stripping(tmp_repo, make_ctx):
    # The `//` of a bare URL must not be treated as a comment marker.
    tmp_repo.write(".env", "API_URL=http://localhost:8000\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert not result.passed
    assert any("localhost" in d for d in _details(result))


def test_python_docstring_mentions_ignored(tmp_repo, make_ctx):
    tmp_repo.write(
        "config.py",
        '"""App config.\n'
        "\n"
        "For local development, point at http://localhost:8000 and set\n"
        "debug: true in your override file.\n"
        '"""\n'
        'API_BASE_URL = "https://api.example.com"\n',
    )
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_vscode_launch_json_excluded(tmp_repo, make_ctx):
    tmp_repo.write(
        ".vscode/launch.json",
        '{"url": "http://localhost:3000", "debug": true}\n',
    )
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_fixture_and_ci_configs_excluded(tmp_repo, make_ctx):
    tmp_repo.write("tests/fixtures/config.yaml", "api_host: localhost\n")
    tmp_repo.write(".github/workflows/ci.yml", "debug: true\n")
    tmp_repo.write(".idea/misc.json", '{"api_host": "localhost"}\n')
    result = check_config(make_ctx(tmp_repo.root))
    assert result.passed


def test_root_deploy_config_still_scanned(tmp_repo, make_ctx):
    # The dir exclusions must not loosen scanning of real deploy config.
    tmp_repo.write("deploy.yaml", "api_host: localhost\n")
    result = check_config(make_ctx(tmp_repo.root))
    assert not result.passed

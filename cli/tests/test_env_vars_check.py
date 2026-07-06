"""missing_env_var: AST variants, JS regex, file:line exactness, fallback."""

from proofloop.checks.env_vars import check_env_vars


def _failed_names(result):
    return [e.detail for e in result.evidence]


def test_subscript_read_is_required(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", 'import os\nkey = os.environ["MUST_HAVE"]\n')
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "missing_env_var"
    assert _failed_names(result) == ["MUST_HAVE"]
    assert result.evidence[0].file == "svc.py"
    assert result.evidence[0].line == 2


def test_environ_get_with_default_is_satisfied(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", 'import os\nx = os.environ.get("OPTIONAL", "fallback")\n')
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert result.passed


def test_environ_get_without_default_is_required(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", 'import os\nx = os.environ.get("NEEDED")\n')
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert not result.passed
    assert _failed_names(result) == ["NEEDED"]


def test_getenv_variants(tmp_repo, make_ctx):
    tmp_repo.write(
        "svc.py",
        'import os\n'
        'a = os.getenv("REQ_ONE")\n'
        'b = os.getenv("OPT_ONE", "default")\n'
        'c = os.getenv("OPT_TWO", default=None)\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["REQ_ONE"]


def test_present_env_var_passes(tmp_repo, make_ctx, scrubbed_env):
    tmp_repo.write("svc.py", 'import os\nkey = os.environ["PRESENT_KEY"]\n')
    env = dict(scrubbed_env, PRESENT_KEY="value-set")
    result = check_env_vars(make_ctx(tmp_repo.root, env=env))
    assert result.passed


def test_file_line_exactness(tmp_repo, make_ctx):
    tmp_repo.write(
        "payments.py",
        '"""Doc."""\n' + "\n" * 11 + 'import os\nKEY = os.environ["STRIPE_API_KEY"]\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert result.evidence[0].file == "payments.py"
    assert result.evidence[0].line == 14
    assert "STRIPE_API_KEY (payments.py:14)" in result.evidence_str()
    assert result.evidence_str().endswith("unset")


def test_js_process_env_and_import_meta(tmp_repo, make_ctx):
    tmp_repo.write(
        "web.js",
        "const key = process.env.API_KEY;\n"
        'const base = process.env["BASE_API"];\n'
        "const mode = import.meta.env.MODE;\n"
        "const dev = import.meta.env.DEV;\n"
        "const node = process.env.NODE_ENV;\n"
        "const flag = import.meta.env.VITE_FLAG;\n",
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    names = set(_failed_names(result))
    assert names == {"API_KEY", "BASE_API", "VITE_FLAG"}
    by_name = {e.detail: e.line for e in result.evidence}
    assert by_name["API_KEY"] == 1
    assert by_name["BASE_API"] == 2
    assert by_name["VITE_FLAG"] == 6


def test_syntax_error_falls_back_to_regex(tmp_repo, make_ctx):
    tmp_repo.write(
        "broken.py",
        'def broken(:\nimport os\nx = os.environ["FALLBACK_VAR"]\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert not result.passed
    assert "FALLBACK_VAR" in _failed_names(result)
    assert result.evidence[0].line == 3


def test_dedupe_keeps_first_reference(tmp_repo, make_ctx):
    tmp_repo.write("a_first.py", 'import os\nx = os.environ["DUP_VAR"]\n')
    tmp_repo.write("z_second.py", 'import os\ny = os.environ["DUP_VAR"]\n')
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert len(result.evidence) == 1
    assert result.evidence[0].file == "a_first.py"


def test_fix_hint_lists_exports(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", 'import os\nk = os.environ["EXPORT_ME"]\n')
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert "export EXPORT_ME=" in result.fix_hint


def test_from_os_import_environ_subscript(tmp_repo, make_ctx):
    tmp_repo.write("svc.py", 'from os import environ\nkey = environ["FROM_IMPORT"]\n')
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["FROM_IMPORT"]
    assert result.evidence[0].line == 2


def test_from_os_import_environ_get(tmp_repo, make_ctx):
    tmp_repo.write(
        "svc.py",
        "from os import environ\n"
        'a = environ.get("NEED_IT")\n'
        'b = environ.get("HAS_DEFAULT", "d")\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["NEED_IT"]


def test_from_os_import_getenv(tmp_repo, make_ctx):
    tmp_repo.write(
        "svc.py",
        "from os import getenv\n"
        'a = getenv("REQ_IMPORTED")\n'
        'b = getenv("OPT_IMPORTED", "d")\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["REQ_IMPORTED"]


def test_import_os_as_alias(tmp_repo, make_ctx):
    tmp_repo.write(
        "svc.py",
        "import os as _os\n"
        'k = _os.environ["ALIASED_SUB"]\n'
        'g = _os.getenv("ALIASED_GET")\n'
        'd = _os.environ.get("ALIASED_DEFAULT", "x")\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert set(_failed_names(result)) == {"ALIASED_SUB", "ALIASED_GET"}


def test_from_os_import_with_aliases(tmp_repo, make_ctx):
    tmp_repo.write(
        "svc.py",
        "from os import environ as env_map, getenv as read_env\n"
        'a = env_map["ENV_ALIAS"]\n'
        'b = read_env("GETENV_ALIAS")\n'
        'c = env_map.get("GET_ALIAS")\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert set(_failed_names(result)) == {"ENV_ALIAS", "GETENV_ALIAS", "GET_ALIAS"}


def test_js_destructuring_reads(tmp_repo, make_ctx):
    tmp_repo.write("web.js", "const { API_KEY, OTHER } = process.env;\n")
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert set(_failed_names(result)) == {"API_KEY", "OTHER"}
    assert all(e.line == 1 for e in result.evidence)


def test_js_destructuring_rename_and_defaults(tmp_repo, make_ctx):
    tmp_repo.write(
        "web.js",
        "const { STRIPE_KEY: key, PORT = 3000, HOST: h = 'x' } = process.env;\n",
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    # Rename reads the LEFT identifier; entries with `=` have defaults.
    assert _failed_names(result) == ["STRIPE_KEY"]


def test_js_optional_chaining(tmp_repo, make_ctx):
    tmp_repo.write(
        "web.js",
        "const a = process.env?.OPT_CHAIN;\n"
        "const b = import.meta.env?.VITE_CHAIN;\n",
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert set(_failed_names(result)) == {"OPT_CHAIN", "VITE_CHAIN"}


def test_js_comments_are_ignored(tmp_repo, make_ctx):
    tmp_repo.write(
        "web.js",
        "// const old = process.env.OLD_VAR;\n"
        "/*\n"
        "const older = process.env.BLOCK_VAR;\n"
        "*/\n"
        "const real = process.env.REAL_VAR; // process.env.TAIL_VAR\n",
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["REAL_VAR"]
    assert result.evidence[0].line == 5


def test_js_comment_markers_inside_strings_kept(tmp_repo, make_ctx):
    tmp_repo.write(
        "web.js",
        'const url = "http://x/" + process.env.AFTER_STRING;\n',
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["AFTER_STRING"]


def test_js_or_and_nullish_fallbacks_are_defaults(tmp_repo, make_ctx):
    tmp_repo.write(
        "web.js",
        "const port = process.env.PORT || 3000;\n"
        "const host = process.env.HOST ?? 'localhost';\n"
        'const base = process.env["BASE"] || "/";\n'
        "const req = process.env.MUST_SET;\n",
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["MUST_SET"]


def test_vue_files_are_scanned(tmp_repo, make_ctx):
    tmp_repo.write(
        "App.vue",
        "<script>\nconst u = import.meta.env.VITE_API_URL;\n</script>\n",
    )
    result = check_env_vars(make_ctx(tmp_repo.root))
    assert _failed_names(result) == ["VITE_API_URL"]
    assert result.evidence[0].line == 2

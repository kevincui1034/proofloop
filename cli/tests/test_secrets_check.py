"""hardcoded_secret: provider patterns, entropy gate, placeholder suppression.

Test vectors are assembled from fragments (e.g. ``"sk_" + "live_" + ...``) so no
contiguous provider-shaped secret literal ever sits in this source file. The
concatenated *runtime* value is identical, so it still exercises proofjury's
scanner when written to a temp file — but GitHub push protection and other
secret scanners see only harmless fragments in the committed source.
"""

from proofjury.checks.secrets import SecretScanner, check_secrets, shannon_entropy

# Synthetic, non-real secrets — assembled so the prefix is split from the body.
_STRIPE = "sk_" + "live_" + "a1B2c3D4e5F6g7H8i9J0k1L2"
_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
_GH = "ghp_" + "Ab1" * 12
_SLACK = "xoxb-" + "123456789012-abcDEF123456"


def _details(result):
    return [e.detail for e in result.evidence]


def test_aws_key_detected(tmp_repo, make_ctx):
    tmp_repo.write("infra.py", f'ACCESS = "{_AWS}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.failure_class == "hardcoded_secret"
    assert any("AWS access key" in d for d in _details(result))
    assert result.evidence[0].file == "infra.py"
    assert result.evidence[0].line == 1


def test_stripe_key_detected(tmp_repo, make_ctx):
    tmp_repo.write("billing.py", f'KEY = "{_STRIPE}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert any("Stripe secret key" in d for d in _details(result))


def test_github_token_detected(tmp_repo, make_ctx):
    tmp_repo.write("ci.py", f'TOK = "{_GH}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert any("GitHub token" in d for d in _details(result))


def test_slack_token_detected(tmp_repo, make_ctx):
    tmp_repo.write("bot.py", f'SLACK = "{_SLACK}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert any("Slack token" in d for d in _details(result))


def test_private_key_header_detected(tmp_repo, make_ctx):
    tmp_repo.write("key.pem", "-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    result = check_secrets(make_ctx(tmp_repo.root))
    assert any("private key material" in d for d in _details(result))


def test_generic_high_entropy_detected(tmp_repo, make_ctx):
    tmp_repo.write("cfg.py", 'api_key = "aB3dE5gH7jK9mN1pQ2sT4vWx"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert any("high-entropy" in d for d in _details(result))


def test_generic_low_entropy_ignored(tmp_repo, make_ctx):
    tmp_repo.write("cfg.py", 'password = "aaaaaaaaaaaaaaaaaaaa"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_secret_value_never_persisted_in_evidence(tmp_repo, make_ctx):
    secret = _STRIPE
    tmp_repo.write("billing.py", f'KEY = "{secret}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert secret not in result.evidence_str()


def test_placeholders_suppressed(tmp_repo, make_ctx):
    tmp_repo.write(
        "cfg.py",
        'a = "changeme-changeme-changeme"\n'
        'api_key = "your-key-here-your-key-here"\n'
        'secret = "<insert-secret-value-here>"\n'
        'token = "${SECRET_TOKEN_FROM_ENV}"\n'
        'password = "example-password-value-1"\n',
    )
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_env_var_reads_not_flagged(tmp_repo, make_ctx):
    tmp_repo.write("cfg.js", "const apiKey = process.env.API_KEY_LONG_NAME;\n")
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_lock_files_skipped(tmp_repo, make_ctx):
    tmp_repo.write("poetry.lock", f'hash = "{_STRIPE}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_binary_files_skipped(tmp_repo, make_ctx):
    tmp_repo.write_bytes("blob.bin", b"\x00\x01" + _STRIPE.encode())
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_shannon_entropy_values():
    assert shannon_entropy("aaaa") == 0.0
    assert shannon_entropy("aB3dE5gH7jK9mN1pQ2sT4vWx") > 4.0


def test_scanner_masks_values():
    scanner = SecretScanner()
    findings = scanner.scan_line(f'key = "{_AWS}"')
    assert findings
    assert _AWS not in findings[0]


def test_keyword_with_trailing_identifier_chars_detected(tmp_repo, make_ctx):
    tmp_repo.write(
        "settings.py",
        'SECRET_KEY = "aB3dE5gH7jK9mN1pQ2sT4vWx"\n'
        'AWS_SECRET_ACCESS_KEY = "7Kd2Rp9Wm4Zx6Qb1Ln8Vt3Yc5Hf0Jg"\n'
        'API_TOKEN_VALUE = "aB3dE5gH7jK9mN1pQ2sT4vWx"\n',
    )
    result = check_secrets(make_ctx(tmp_repo.root))
    assert not result.passed
    lines = {e.line for e in result.evidence}
    assert lines == {1, 2, 3}


def test_random_hex_secret_detected(tmp_repo, make_ctx):
    # Hex tops out at 4.0 bits/char, so the old flat `> 4.0` gate could
    # never fire on hex values; the per-charset threshold catches them.
    tmp_repo.write("cfg.py", 'api_key = "9f8a6c2e4b1d7f3a5c8e0b6d2f4a9c1e"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert not result.passed
    assert any("high-entropy" in d for d in _details(result))


def test_repeated_chars_and_english_words_not_flagged(tmp_repo, make_ctx):
    tmp_repo.write(
        "cfg.py",
        'password = "aaaaaaaaaaaaaaaa"\n'
        'api_key = "correct horse battery staple"\n',
    )
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_gitignored_file_not_flagged(tmp_repo, make_ctx):
    tmp_repo.write(".gitignore", ".env.local\n")
    tmp_repo.write(".env.local", f'STRIPE_SECRET="{_STRIPE}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert result.passed


def test_same_file_not_gitignored_is_flagged(tmp_repo, make_ctx):
    tmp_repo.write(".env.local", f'STRIPE_SECRET="{_STRIPE}"\n')
    result = check_secrets(make_ctx(tmp_repo.root))
    assert not result.passed
    assert result.evidence[0].file == ".env.local"


def test_non_git_dir_ignores_gitignore(tmp_path, make_ctx):
    # Outside a git repo, current scan-everything behavior is preserved.
    (tmp_path / ".gitignore").write_text(".env.local\n")
    (tmp_path / ".env.local").write_text(f'STRIPE_SECRET="{_STRIPE}"\n')
    result = check_secrets(make_ctx(tmp_path))
    assert not result.passed

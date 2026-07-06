"""agent_source detection from environment markers."""

from proofloop.agent_detect import detect_agent_source


def test_claude_via_claudecode_flag():
    assert detect_agent_source({"CLAUDECODE": "1"}) == "claude"


def test_claude_via_entrypoint():
    assert detect_agent_source({"CLAUDE_CODE_ENTRYPOINT": "cli"}) == "claude"


def test_cursor_via_trace_id():
    assert detect_agent_source({"CURSOR_TRACE_ID": "abc"}) == "cursor"


def test_cursor_via_term_program():
    assert detect_agent_source({"TERM_PROGRAM": "cursor"}) == "cursor"


def test_codex_via_env_prefix():
    assert detect_agent_source({"CODEX_SANDBOX": "1"}) == "codex"


def test_override_wins():
    env = {"PROOFLOOP_AGENT_SOURCE": "codex", "CLAUDECODE": "1"}
    assert detect_agent_source(env) == "codex"


def test_unknown_by_default():
    assert detect_agent_source({"TERM_PROGRAM": "iTerm.app", "HOME": "/x"}) == "unknown"

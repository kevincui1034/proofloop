"""Judge layer: deterministic templates, provider adapters, factory, fallback."""

import json

import httpx
import pytest

from proofloop import config
from proofloop.checks.base import CheckResult, Evidence
from proofloop.judge import (
    AnthropicJudge,
    DeterministicJudge,
    JudgeInput,
    MockJudge,
    OpenAIJudge,
    OpenRouterJudge,
    get_judge,
)
from proofloop.judge.deterministic import MODEL_ID as DETERMINISTIC_MODEL_ID


def _env_failure() -> CheckResult:
    return CheckResult(
        name="env_vars",
        passed=False,
        failure_class="missing_env_var",
        evidence=[
            Evidence(file="payments.py", line=14, detail="STRIPE_API_KEY"),
            Evidence(file="db.py", line=3, detail="DATABASE_URL"),
        ],
        evidence_suffix="unset",
        fix_hint="Set the missing env vars in the deploy environment: export STRIPE_API_KEY=<value>; export DATABASE_URL=<value>",
    )


def _tests_failure() -> CheckResult:
    return CheckResult(
        name="tests",
        passed=False,
        failure_class="tests_not_run",
        evidence=[
            Evidence(
                file=".proofloop/session.json",
                line=1,
                detail="no test run recorded for this worktree",
            )
        ],
        fix_hint="Run: proofloop run tests -- pytest",
    )


def _judge_input(priors=None) -> JudgeInput:
    return JudgeInput(
        action="deploy",
        repo_id="demo-app",
        failures=[_env_failure(), _tests_failure()],
        git_summary="not a git repository",
        priors=priors or [],
    )


def test_deterministic_diagnosis_cites_vars_and_lines():
    output = DeterministicJudge().diagnose(_judge_input())
    assert output.model_id == DETERMINISTIC_MODEL_ID
    assert output.cost_usd == 0.0
    assert "Blocking deploy —" in output.diagnosis
    assert "STRIPE_API_KEY, DATABASE_URL referenced" in output.diagnosis
    assert "payments.py:14" in output.diagnosis
    assert "db.py:3" in output.diagnosis
    assert "the first request will crash" in output.diagnosis
    assert "Tests have not run against this worktree" in output.diagnosis
    assert any("export STRIPE_API_KEY" in step for step in output.fix_steps)
    assert any("proofloop run tests" in step for step in output.fix_steps)


def test_deterministic_severity_orders_env_first():
    output = DeterministicJudge().diagnose(
        JudgeInput(
            action="deploy",
            repo_id="demo-app",
            failures=[_tests_failure(), _env_failure()],  # reversed on purpose
            git_summary="",
        )
    )
    assert output.diagnosis.index("STRIPE_API_KEY") < output.diagnosis.index("Tests have not run")


def test_deterministic_prepends_seen_before_with_priors(record_factory):
    prior = record_factory("chk_001")
    output = DeterministicJudge().diagnose(_judge_input(priors=[prior]))
    assert output.diagnosis.startswith("Seen before — matches chk_001")
    assert "same STRIPE_API_KEY failure" in output.diagnosis


def test_judge_input_prompt_text_is_stable_and_complete(record_factory):
    ji = _judge_input(priors=[record_factory("chk_001")])
    text = ji.to_prompt_text()
    assert text == ji.to_prompt_text()  # deterministic
    assert "action: deploy" in text
    assert "env_vars [missing_env_var]" in text
    assert "STRIPE_API_KEY (payments.py:14)" in text
    assert "chk_001" in text


def test_openrouter_success_parses_and_writes_ledger(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"diagnosis": "LLM diagnosis", "fix_steps": ["step one"]}
                            )
                        }
                    }
                ],
                "usage": {"cost": 0.00042},
            },
        )

    judge = OpenRouterJudge(
        api_key="test-key",
        model="openai/gpt-4o-mini",
        transport=httpx.MockTransport(handler),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.diagnosis == "LLM diagnosis"
    assert output.fix_steps == ["step one"]
    assert output.model_id == "openai/gpt-4o-mini"
    assert output.cost_usd == 0.00042
    assert seen["auth"] == "Bearer test-key"
    assert "STRIPE_API_KEY (payments.py:14)" in seen["body"]["messages"][1]["content"]
    ledger_lines = (tmp_path / ".proofloop" / "ledger.jsonl").read_text().splitlines()
    entry = json.loads(ledger_lines[0])
    assert entry["model"] == "openai/gpt-4o-mini"
    assert entry["cost_usd"] == 0.00042


def test_openrouter_unstructured_reply_keeps_text(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "plain text verdict"}}],
                "usage": {"cost": 0.0001},
            },
        )

    judge = OpenRouterJudge(api_key="k", transport=httpx.MockTransport(handler))
    output = judge.diagnose(_judge_input())
    assert output.diagnosis == "plain text verdict"
    assert any("export STRIPE_API_KEY" in s for s in output.fix_steps)


def test_openrouter_error_falls_back_to_deterministic(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    judge = OpenRouterJudge(
        api_key="k",
        transport=httpx.MockTransport(handler),
        fallback=DeterministicJudge(),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.model_id == DETERMINISTIC_MODEL_ID
    assert "STRIPE_API_KEY" in output.diagnosis


def test_openrouter_http_error_falls_back():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    judge = OpenRouterJudge(api_key="k", transport=httpx.MockTransport(handler))
    output = judge.diagnose(_judge_input())
    assert output.model_id == DETERMINISTIC_MODEL_ID


def test_factory_selects_openrouter_when_key_present(tmp_path):
    judge = get_judge({"OPENROUTER_API_KEY": "k"}, root=tmp_path)
    assert isinstance(judge, OpenRouterJudge)
    assert judge.model == "openai/gpt-4o-mini"


def test_factory_honors_model_override(tmp_path):
    judge = get_judge(
        {"OPENROUTER_API_KEY": "k", "PROOFLOOP_JUDGE_MODEL": "meta/cheap-model"},
        root=tmp_path,
    )
    assert judge.model == "meta/cheap-model"


def test_factory_deterministic_without_key():
    assert isinstance(get_judge({}), DeterministicJudge)


def test_factory_deterministic_with_no_llm_flag():
    judge = get_judge({"OPENROUTER_API_KEY": "k", "PROOFLOOP_NO_LLM": "1"})
    assert isinstance(judge, DeterministicJudge)


def test_mock_judge_records_calls():
    mock = MockJudge()
    ji = _judge_input()
    output = mock.diagnose(ji)
    assert output.diagnosis == "mock diagnosis"
    assert mock.calls == [ji]


# --------------------------------------------------------------------------
# AnthropicJudge — Messages API wire shape, price table, ledger, fallback
# --------------------------------------------------------------------------


def test_anthropic_success_parses_and_writes_ledger(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["x_api_key"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"diagnosis": "Claude diagnosis", "fix_steps": ["fix a", "fix b"]}
                        ),
                    }
                ],
                "usage": {"input_tokens": 1000, "output_tokens": 200},
            },
        )

    judge = AnthropicJudge(
        api_key="sk-ant-key",
        transport=httpx.MockTransport(handler),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.diagnosis == "Claude diagnosis"
    assert output.fix_steps == ["fix a", "fix b"]
    assert output.model_id == "claude-haiku-4-5"
    # 1000/1e6 * 1.00 + 200/1e6 * 5.00 = 0.002 (non-zero, from the PRICE table)
    assert output.cost_usd == pytest.approx(0.002)
    assert output.cost_usd > 0
    # request shape
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["x_api_key"] == "sk-ant-key"
    assert seen["version"] == "2023-06-01"
    assert seen["body"]["max_tokens"] == 700
    assert seen["body"]["system"].startswith("You are Proofloop's deploy-readiness judge")
    # system is a top-level field, never a message role
    assert [m["role"] for m in seen["body"]["messages"]] == ["user"]
    assert "STRIPE_API_KEY (payments.py:14)" in seen["body"]["messages"][0]["content"]
    # ledger: computed non-zero cost
    ledger = json.loads(
        (tmp_path / ".proofloop" / "ledger.jsonl").read_text().splitlines()[0]
    )
    assert ledger["model"] == "claude-haiku-4-5"
    assert ledger["cost_usd"] == pytest.approx(0.002)


def test_anthropic_default_model_is_haiku():
    assert AnthropicJudge(api_key="k").model == "claude-haiku-4-5"


def test_anthropic_unknown_model_costs_zero(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "claude-experimental",
                "content": [{"type": "text", "text": "plain verdict"}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    judge = AnthropicJudge(
        api_key="k",
        model="claude-experimental",
        transport=httpx.MockTransport(handler),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.cost_usd == 0.0  # unknown model → 0.0
    assert output.diagnosis == "plain verdict"
    assert any("export STRIPE_API_KEY" in s for s in output.fix_steps)


def test_anthropic_error_falls_back_to_deterministic(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    judge = AnthropicJudge(
        api_key="k",
        transport=httpx.MockTransport(handler),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.model_id == DETERMINISTIC_MODEL_ID
    assert "STRIPE_API_KEY" in output.diagnosis
    assert not (tmp_path / ".proofloop" / "ledger.jsonl").exists()


# --------------------------------------------------------------------------
# OpenAIJudge — chat/completions, PRICE table, ledger, fallback
# --------------------------------------------------------------------------


def test_openai_success_parses_and_writes_ledger(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"diagnosis": "OpenAI diagnosis", "fix_steps": ["step x"]}
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    judge = OpenAIJudge(
        api_key="sk-openai",
        transport=httpx.MockTransport(handler),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.diagnosis == "OpenAI diagnosis"
    assert output.fix_steps == ["step x"]
    assert output.model_id == "gpt-4o-mini"
    # 1000/1e6 * 0.15 + 500/1e6 * 0.60 = 0.00045 (non-zero, from the PRICE table)
    assert output.cost_usd == pytest.approx(0.00045)
    assert output.cost_usd > 0
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-openai"
    assert seen["body"]["max_tokens"] == 700
    assert "usage" not in seen["body"]  # OpenAI: do NOT send usage.include
    assert seen["body"]["messages"][0]["role"] == "system"
    assert "STRIPE_API_KEY (payments.py:14)" in seen["body"]["messages"][1]["content"]
    ledger = json.loads(
        (tmp_path / ".proofloop" / "ledger.jsonl").read_text().splitlines()[0]
    )
    assert ledger["model"] == "gpt-4o-mini"
    assert ledger["cost_usd"] == pytest.approx(0.00045)


def test_openai_default_model():
    assert OpenAIJudge(api_key="k").model == "gpt-4o-mini"


def test_openai_error_falls_back_to_deterministic(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    judge = OpenAIJudge(
        api_key="k",
        transport=httpx.MockTransport(handler),
        root=tmp_path / ".proofloop",
    )
    output = judge.diagnose(_judge_input())
    assert output.model_id == DETERMINISTIC_MODEL_ID
    assert not (tmp_path / ".proofloop" / "ledger.jsonl").exists()


# --------------------------------------------------------------------------
# factory selection across providers
# --------------------------------------------------------------------------


def test_factory_selects_anthropic_from_env(tmp_path):
    judge = get_judge({"ANTHROPIC_API_KEY": "sk-ant"}, root=tmp_path)
    assert isinstance(judge, AnthropicJudge)
    assert judge.model == "claude-haiku-4-5"


def test_factory_selects_openai_from_env(tmp_path):
    judge = get_judge({"OPENAI_API_KEY": "sk-openai"}, root=tmp_path)
    assert isinstance(judge, OpenAIJudge)
    assert judge.model == "gpt-4o-mini"


def test_factory_explicit_provider_plus_config_key(tmp_path):
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "PROOFLOOP_JUDGE_PROVIDER": "anthropic",
    }
    config.save_judge_config("anthropic", "stored-ant-key", env=env)
    judge = get_judge(env, root=tmp_path)
    assert isinstance(judge, AnthropicJudge)
    assert judge.api_key == "stored-ant-key"


def test_factory_stored_config_only_selects_adapter(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    config.save_judge_config("openai", "stored-openai", model="gpt-4o-mini", env=env)
    judge = get_judge(env, root=tmp_path)
    assert isinstance(judge, OpenAIJudge)
    assert judge.api_key == "stored-openai"


def test_factory_no_llm_flag_beats_stored_config(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "PROOFLOOP_NO_LLM": "1"}
    config.save_judge_config("anthropic", "k", env=env)
    assert isinstance(get_judge(env), DeterministicJudge)

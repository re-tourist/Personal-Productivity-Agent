"""Real SDK/structured-parser integration over an in-memory HTTP transport: ZERO live calls."""
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from productivity_agent.domain.agent_intent import AgentIntent
from productivity_agent.providers.qwen import build_qwen_model
from productivity_agent.providers.qwen_meter import QwenMeter, QwenValidationError, ValidationBudget
from scripts.validate_qwen_agent import SCENARIOS, checked_profile, resume_report, run_live


def completion(arguments):
    return {"id": "offline-response", "object": "chat.completion", "created": 0,
            "model": "qwen3.7-flash", "choices": [{"index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": "", "tool_calls": [{
                    "id": "offline-call", "type": "function",
                    "function": {"name": "AgentIntent", "arguments": json.dumps(arguments)},
                }]}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


@pytest.fixture
def safe_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "offline-synthetic-secret")
    monkeypatch.setenv("PPA_MODEL", "qwen3.7-flash")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def test_sdk_payload_forced_function_non_thinking_usage_and_hard_call_limit(safe_env):
    payloads = []

    def handle(request):
        payloads.append(json.loads(request.content))
        assert request.url.path == "/compatible-mode/v1/chat/completions"
        return httpx.Response(200, json=completion({"action": "list_tasks"}))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        model = build_qwen_model(http_client=client)
        meter = QwenMeter(model, ValidationBudget(max_calls=1))
        extractor = meter.structured(AgentIntent)
        assert extractor.invoke([("human", "查看我的任务")]).action == "list_tasks"
        assert model.max_retries == 0
        assert payloads[0]["max_completion_tokens"] == 600
        assert payloads[0]["enable_thinking"] is False
        assert payloads[0]["tool_choice"]["function"]["name"] == "AgentIntent"
        assert payloads[0]["parallel_tool_calls"] is False
        assert meter.records[0]["input_tokens"] == 100
        assert meter.records[0]["output_tokens"] == 50
        assert meter.records[0]["estimated_cny"] == 0.00006
        with pytest.raises(QwenValidationError):
            extractor.invoke([("human", "再次查询")])
        assert len(payloads) == 1
        assert "offline-synthetic-secret" not in json.dumps(meter.records)


@pytest.mark.parametrize("failure", ["timeout", "invalid_schema", "unknown_usage"])
def test_sdk_failures_keep_budget_and_never_log_raw_secrets(safe_env, failure):
    calls = []

    def handle(request):
        calls.append(1)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline-synthetic-secret", request=request)
        response = completion({"action": "erase_all_files"} if failure == "invalid_schema"
                              else {"action": "list_tasks"})
        if failure == "unknown_usage":
            response.pop("usage")
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        meter = QwenMeter(build_qwen_model(http_client=client), ValidationBudget())
        extractor = meter.structured(AgentIntent)
        if failure == "unknown_usage":
            assert extractor.invoke([("human", "查看任务")]).action == "list_tasks"
            assert meter.records[0]["input_tokens"] is None
            assert meter.records[0]["estimated_cny"] is None
        else:
            with pytest.raises(QwenValidationError) as error:
                extractor.invoke([("human", "查看任务")])
            assert "offline-synthetic-secret" not in str(error.value)
        with pytest.raises(QwenValidationError):
            extractor.invoke([("human", "不得自动重试")])
        assert len(calls) == 1
        assert len(meter.records) == 1
        assert "offline-synthetic-secret" not in json.dumps(meter.records)


def test_preflight_rejects_oversized_prompt_and_monetary_limit(safe_env):
    def no_network(request):
        pytest.fail("Budget guard must reject before transport")

    with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
        model = build_qwen_model(http_client=client)
        with pytest.raises(QwenValidationError):
            QwenMeter(model, ValidationBudget(max_cny=Decimal("0.00001"))).structured(AgentIntent).invoke(
                [("human", "查看任务")])
        with pytest.raises(QwenValidationError):
            QwenMeter(model, ValidationBudget()).structured(AgentIntent).invoke([("human", "中" * 8000)])


def test_live_profile_does_not_silently_change_model_or_region():
    assert checked_profile("qwen3.7-flash", "https://demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")["region"] == "cn-beijing"
    for model, endpoint in [
        ("qwen3.7-max", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("qwen3.7-flash", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        ("qwen3.7-flash", "https://user:secret@dashscope.aliyuncs.com/compatible-mode/v1"),
        ("qwen3.7-flash", "https://untrusted.example/compatible-mode/v1"),
    ]:
        with pytest.raises(ValueError):
            checked_profile(model, endpoint)


def test_validation_script_is_dry_by_default_and_live_requires_explicit_budget():
    script = Path(__file__).parents[1] / "scripts/validate_qwen_agent.py"
    result = subprocess.run([sys.executable, str(script)], check=False, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["status"] == "NOT_RUN_REQUIRES_USER_AUTHORIZATION"
    assert plan["max_calls"] == 12
    result = subprocess.run([sys.executable, str(script), "--live"], check=False,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert "explicit approved limits" in result.stderr


def test_all_validation_scenarios_execute_over_offline_http_fixtures(safe_env):
    """Validate runner/DB/assertions, NOT Qwen quality: all HTTP responses are synthetic."""
    from datetime import datetime, timedelta

    def handle(request):
        payload = json.loads(request.content)
        if any(t["function"]["name"] == "AgentIntent" for t in payload["tools"]):
            context = json.loads(payload["messages"][-1]["content"])
            text = context["message"]
            due = (datetime.fromisoformat(context["reference_now"]) + timedelta(days=1)).replace(
                hour=15, minute=0, second=0, microsecond=0).isoformat()
            result = {"action": "create_task", "title": "准备组会", "at": due}
            if "查看我的任务" in text:
                result = {"action": "list_tasks"}
            elif "删除系统文件" in text:
                result = {"action": "unsupported"}
            elif "二十五点" in text or ("帮我创建一个" in text and "明天" not in text):
                result["at"] = None
            elif "安排一小时" in text:
                result.update(action="check_calendar", duration_minutes=60)
            return httpx.Response(200, json=completion(result))
        response = completion({})
        if any(m["role"] == "tool" for m in payload["messages"]):
            response["choices"][0]["message"] = {"role": "assistant", "content": "待办：准备组会。"}
            response["choices"][0]["finish_reason"] = "stop"
        else:
            response["choices"][0]["message"]["tool_calls"][0]["function"] = {
                "name": "list_tasks", "arguments": "{}"}
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        meter = QwenMeter(build_qwen_model(http_client=client), ValidationBudget())
        report = {"cases": []}
        run_live(meter, report)
        assert len(report["cases"]) == len(SCENARIOS)
        assert all(row["success"] for row in report["cases"]), report
        assert len(meter.records) == 10
        assert report["cases"][-1]["scope"] == "legacy_readonly_react_only_not_unified_planning"
        assert report["cases"][-1]["actual_tools"] == ["list_tasks"]


def test_resume_preserves_call_count_and_rejects_unknown_usage(tmp_path):
    profile = {"model": "qwen3.7-flash", "region": "cn-beijing", "endpoint": "workspace"}
    ledger = {"profile": profile, "status": "PARTIAL_OR_FAILED", "budget": {"max_calls": 12},
              "totals": {"calls": 4}, "calls": [
                  {"attempt": i+1, "status": "parsed", "input_tokens": 600, "output_tokens": 80}
                  for i in range(4)]}
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    result = resume_report(path, profile)
    assert len(result["calls"]) == 4
    assert result["continuations"][-1]["calls_before"] == 4
    ledger["calls"][0]["input_tokens"] = None
    path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ValueError):
        resume_report(path, profile)

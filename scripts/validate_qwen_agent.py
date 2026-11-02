"""Dry by default. A single authorized, bounded run against the existing unified graph."""
import argparse
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from productivity_agent.providers.qwen import DEFAULT_BEIJING_BASE_URL, DEFAULT_QWEN_MODEL
from productivity_agent.providers.qwen_meter import QwenMeter, ValidationBudget

PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/qwen3-7-flash"
SCENARIOS = ["single_task", "clarification", "calendar", "reject", "unsupported",
             "invalid_time", "query_and_replay", "legacy_readonly_feedback"]


def checked_profile(model, endpoint):
    url = urlsplit(endpoint)
    host = url.hostname or ""
    valid_host = host == "dashscope.aliyuncs.com" or re.fullmatch(
        r"[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com", host)
    if (model not in {DEFAULT_QWEN_MODEL, "qwen3.7-flash-2026-07-15"} or not valid_host
            or url.scheme != "https" or url.port not in {None, 443}
            or url.username or url.password or url.query or url.fragment
            or url.path.rstrip("/") != "/compatible-mode/v1"):
        raise ValueError("Validation requires the reviewed Beijing qwen3.7-flash profile")
    return {"model": model, "region": "cn-beijing", "endpoint": "workspace" if ".maas." in host else "legacy"}


def plan():
    return {"status": "NOT_RUN_REQUIRES_USER_AUTHORIZATION", "scenarios": SCENARIOS,
            "max_calls": 12, "input_reserve_per_call": 8000, "max_completion_tokens": 600,
            "output_reserve_per_call": 610, "max_input_total": 96000,
            "max_output_reserve_total": 7320, "max_tokens_reserved": 103320,
            "estimated_reserved_ceiling_cny": 0.025056, "approval_budget_cny": 0.05,
            "input_cny_per_million": 0.2, "output_cny_per_million": 0.8,
            "pricing_source": PRICE_SOURCE, "retries": 0,
            "note": "Beijing <=32K list price, no cache/free-quota discounts assumed; billing receipt unavailable."}


def run_live(meter, report):
    from fastapi.testclient import TestClient
    from langchain_core.messages import HumanMessage, ToolMessage

    from productivity_agent.api.app import create_app
    from productivity_agent.api.assistant import config
    from productivity_agent.domain.agent_intent import AgentIntent
    from productivity_agent.tools.productivity import MockProductivityBackend
    from productivity_agent.workflows.tool_agent import build_tool_agent

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    due = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    root = Path(__file__).resolve().parents[1]
    cache = root / ".pytest_cache"
    if not cache.resolve().is_relative_to(root):
        raise ValueError("Test cache must stay inside checkout")
    cache.mkdir(exist_ok=True)
    backend = MockProductivityBackend(events=[{
        "title": "验收模拟会议", "start_at": (due + timedelta(minutes=30)).isoformat(),
        "end_at": (due + timedelta(minutes=90)).isoformat(),
    }])
    with tempfile.TemporaryDirectory(prefix="qwen-validation-", dir=cache) as directory:
        assert Path(directory).resolve().parent == cache.resolve()
        # Isolation only: actual parser is the real metered Qwen client. No fake responses.
        with patch.dict(os.environ, PPA_DATA_DIR=directory, PPA_ENABLE_LIVE_QWEN="0",
                        LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false"):
            app = create_app(api_token="", session_extractor=meter.structured(AgentIntent), session_backend=backend)
            with TestClient(app) as api:
                def session():
                    r = api.post("/v1/assistant/sessions", json={})
                    assert r.status_code == 201
                    return r.json()["thread_id"]

                def ask(tid, text):
                    r = api.post(f"/v1/assistant/sessions/{tid}/messages", json={
                        "message": text, "reference_now": now.isoformat(), "timezone": "Asia/Shanghai",
                        "message_id": str(uuid.uuid4()),
                    })
                    assert r.status_code == 200
                    snapshot = api.portal.call(app.state.assistant_graph.aget_state, config(tid))
                    report["cases"][-1].setdefault("turns", []).append({
                        "input_intent": text, "reference_now": now.isoformat(), "timezone": "Asia/Shanghai",
                        "structured_parameters": snapshot.values.get("intent"),
                        "selected_workflow": (snapshot.values.get("intent") or {}).get("action"),
                        "status": r.json()["status"], "reply": r.json()["reply"],
                        "business_result": r.json()["result"],
                        "parameter_validation": "clarification_requested" if r.json()["status"] ==
                        "clarification_required" else "parse_failed" if r.json()["status"] ==
                        "parse_failed" else "accepted_or_unsupported",
                    })
                    return r.json()

                def confirm(tid, pending, approved):
                    r = api.post(f"/v1/assistant/sessions/{tid}/decision", json={
                        "operation_id": pending["approval"]["operation_id"], "approved": approved,
                    })
                    assert r.status_code == 200
                    report["cases"][-1].setdefault("decisions", []).append({
                        "approved": approved, "status": r.json()["status"], "result": r.json()["result"],
                    })
                    return r.json()

                task_tid, task_pending = None, None
                for name in SCENARIOS:
                    if meter.stopped:
                        break
                    row = {"scenario": name, "success": False}
                    report["cases"].append(row)
                    meter.scenario = name
                    begin, start = len(meter.records), perf_counter()
                    try:
                        count = api.get("/v1/tasks").json()["count"]
                        if name == "single_task":
                            task_tid = session()
                            task_pending = ask(task_tid, "明天下午三点帮我创建一个准备组会的任务。")
                            assert task_pending["status"] == "awaiting_approval"
                            assert task_pending["approval"]["title"] == "准备组会"
                            assert datetime.fromisoformat(task_pending["approval"]["due_at"]) == due
                            assert api.get("/v1/tasks").json()["count"] == count
                            created = confirm(task_tid, task_pending, True)
                            assert created["status"] == "created"
                            assert created["result"]["task"] in api.get("/v1/tasks").json()["items"]
                        elif name == "clarification":
                            tid = session()
                            assert ask(tid, "帮我创建一个准备组会的任务。 ")["status"] == "clarification_required"
                            pending = ask(tid, "明天下午三点。")
                            assert pending["status"] == "awaiting_approval"
                            assert pending["approval"]["title"] == "准备组会"
                            assert datetime.fromisoformat(pending["approval"]["due_at"]) == due
                            confirm(tid, pending, False)
                            assert api.get("/v1/tasks").json()["count"] == count
                        elif name == "calendar":
                            result = ask(session(), "帮我看看明天下午三点能不能安排一小时组会。")
                            assert result["result"]["calendar"]["suggested_start"] == (due + timedelta(minutes=90)).isoformat()
                            assert api.get("/v1/tasks").json()["count"] == count
                        elif name == "reject":
                            tid = session()
                            pending = ask(tid, "明天下午三点提醒我准备组会。")
                            assert confirm(tid, pending, False)["status"] == "cancelled"
                            assert api.get("/v1/tasks").json()["count"] == count
                        elif name in {"unsupported", "invalid_time"}:
                            text = "帮我删除系统文件。" if name == "unsupported" else "明天下午二十五点提醒我准备组会。"
                            result = ask(session(), text)
                            assert result["status"] in {"unsupported", "clarification_required", "parse_failed"}
                            assert result["approval"] is None
                            assert api.get("/v1/tasks").json()["count"] == count
                        elif name == "query_and_replay":
                            assert confirm(task_tid, task_pending, True)["status"] == "created"
                            result = ask(task_tid, "查看我的任务。")
                            assert any(t["title"] == "准备组会" for t in result["result"]["tasks"])
                            assert api.get("/v1/tasks").json()["count"] == count
                        else:
                            # A separate EXISTING read-only ReAct diagnostic, not unified planning.
                            tool_backend = MockProductivityBackend(tasks=api.get("/v1/tasks").json()["items"])
                            graph = build_tool_agent(meter, tool_backend, max_model_calls=3)
                            result = graph.invoke({"messages": [HumanMessage(content=
                                "先调用 list_tasks 查询，然后依据工具结果告诉我待办标题；不要检查日历，不要创建任务。")],
                                "reference_now": now.isoformat()})
                            observed = [m for m in result["messages"] if isinstance(m, ToolMessage)]
                            assert any(m.name == "list_tasks" for m in observed)
                            assert "准备组会" in str(result["messages"][-1].content)
                            row["tool_result_observed"] = True
                            row["actual_tools"] = [m.name if m.name in {
                                "list_tasks", "list_calendar_events", "check_calendar_conflict",
                            } else "unrecognized" for m in observed]
                            row["final_answer"] = str(result["messages"][-1].content)[:1000]
                            row["scope"] = "legacy_readonly_react_only_not_unified_planning"
                            assert api.get("/v1/tasks").json()["count"] == count
                        row["success"] = True
                    except Exception:  # noqa: BLE001 -- never put SDK errors/headers in reports.
                        row["error"] = "scenario_assertion_or_execution_failed"
                    finally:
                        row["latency_ms"] = round((perf_counter() - start) * 1000, 2)
                        row["model_calls"] = len(meter.records) - begin
                        calls = meter.records[begin:]
                        row["unknown_usage_calls"] = sum(c["input_tokens"] is None for c in calls)
                        row["input_tokens"] = None if row["unknown_usage_calls"] else sum(
                            c["input_tokens"] for c in calls)
                        row["output_tokens"] = None if row["unknown_usage_calls"] else sum(
                            c["output_tokens"] for c in calls)
                        row["estimated_cny_known_usage"] = round(sum(
                            c["estimated_cny"] or 0 for c in calls), 9)
                        row["actual_task_count"] = api.get("/v1/tasks").json()["count"]
                        meter._save()
                    if not row["success"]:
                        break  # No automatic repairs/retries, and no extra billable attempts.


def serve_web(meter, report):
    """Test-only loopback UI shares this run's meter; never grants another 12 calls."""
    import socket

    import uvicorn

    from productivity_agent.api.app import create_app
    from productivity_agent.domain.agent_intent import AgentIntent
    from productivity_agent.services.task_store import SQLiteTaskStore

    cache = Path(__file__).resolve().parents[1] / ".pytest_cache"
    with tempfile.TemporaryDirectory(prefix="qwen-web-", dir=cache) as directory:
        assert Path(directory).resolve().parent == cache.resolve()
        with patch.dict(os.environ, PPA_DATA_DIR=directory, PPA_ENABLE_LIVE_QWEN="0",
                        LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false"):
            app = create_app(api_token="", session_extractor=meter.structured(AgentIntent))
            server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))

            @app.post("/__validation_stop", include_in_schema=False)
            async def stop():
                server.should_exit = True
                return {"stopping": True}

            meter.scenario = "web_demo"
            begin = len(meter.records)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                sock.listen(128)
                if report.get("web_demo"):
                    report.setdefault("previous_web_runs", []).append(report["web_demo"])
                report["web_demo"] = {"status": "RUNNING", "remaining_calls": 12 - begin}
                meter._save()
                print(f"WEB_VALIDATION_URL=http://127.0.0.1:{sock.getsockname()[1]}/", flush=True)
                server.run(sockets=[sock])
            tasks = SQLiteTaskStore(Path(directory) / "tasks.sqlite").list_tasks()
            report["web_demo"].update(status="STOPPED", model_calls=len(meter.records)-begin,
                                       verified_tasks=tasks, verified_task_count=len(tasks))
            meter._save()


def resume_report(path, profile):
    """Only known, accounted calls can resume; unknown usage fails closed."""
    report = json.loads(path.read_text(encoding="utf-8"))
    calls = report.get("calls", [])
    if (report.get("profile") != profile or not calls or len(calls) >= 12
            or report.get("totals", {}).get("calls") != len(calls)
            or report.get("budget", {}).get("max_calls") != 12
            or any(c.get("attempt") != i + 1 or c.get("status") not in {"parsed", "received"}
                   or type(c.get("input_tokens")) is not int
                   or type(c.get("output_tokens")) is not int for i, c in enumerate(calls))):
        raise ValueError("Cannot safely resume this ledger")
    report.setdefault("continuations", []).append({"calls_before": len(calls),
        "scope": "web_only_same_authorized_budget", "previous_status": report["status"]})
    report["status"] = "PARTIAL_WITH_WEB_CONTINUATION"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--web-demo", action="store_true", help="Shares the SAME total budget")
    parser.add_argument("--resume-web-only", action="store_true", help="Retain all calls in an existing ledger")
    parser.add_argument("--approved-max-calls", type=int)
    parser.add_argument("--approved-max-cny", type=Decimal)
    parser.add_argument("--out", type=Path, default=Path("reports/task05/online-acceptance.json"))
    args = parser.parse_args()
    if not args.live:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return 0  # No credential loading, client construction or network activity.
    if args.approved_max_calls != 12 or args.approved_max_cny != Decimal("0.05"):
        parser.error("Live run needs separate user authorization and explicit approved limits: 12 calls / CNY 0.05")
    logging.disable(logging.CRITICAL)  # SDK wire/debug logs must not disclose headers or workspace IDs.
    load_dotenv(override=False)
    profile = checked_profile(os.getenv("PPA_MODEL", DEFAULT_QWEN_MODEL),
                              os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BEIJING_BASE_URL))
    if not os.getenv("DASHSCOPE_API_KEY", "").strip():
        parser.error("DASHSCOPE_API_KEY is not configured")
    from productivity_agent.providers.qwen import build_qwen_model

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = resume_report(args.out, profile) if args.resume_web_only else {
        "status": "RUNNING", "profile": profile, "budget": plan(), "cases": [],
        "calls": [], "actual_billed_cny": None}
    # Exclusive output creation prevents silently rerunning/overwriting a previous approval run.
    with args.out.open("r+" if args.resume_web_only else "x", encoding="utf-8") as output:
        def save(records):
            report["calls"] = list(records)
            output.seek(0)
            serialized = json.dumps(report, ensure_ascii=False, indent=2)
            secret = os.getenv("DASHSCOPE_API_KEY", "").strip()
            if secret:
                serialized = serialized.replace(secret, "[REDACTED]")
            serialized = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", serialized)
            output.write(serialized)
            output.truncate()
            output.flush()
            os.fsync(output.fileno())

        meter = QwenMeter(build_qwen_model(), ValidationBudget(), save)
        meter.records = list(report["calls"])
        try:
            if not args.resume_web_only:
                run_live(meter, report)
                passed = sum(c["success"] for c in report["cases"])
                report["status"] = "PASS" if passed == len(SCENARIOS) else "PARTIAL_OR_FAILED"
            if args.web_demo and not meter.stopped and len(meter.records) < 12:
                serve_web(meter, report)
        except Exception:  # noqa: BLE001 -- safe validation-report boundary, no SDK traceback.
            report["status"] = "STOPPED_ON_ERROR"
        finally:
            report["totals"] = {
                "calls": len(meter.records),
                "unknown_usage_calls": sum(c["input_tokens"] is None for c in meter.records),
                "known_input_tokens": sum(c["input_tokens"] or 0 for c in meter.records),
                "known_output_tokens": sum(c["output_tokens"] or 0 for c in meter.records),
                "estimated_cny_known_usage": round(sum(c["estimated_cny"] or 0 for c in meter.records), 9),
                "reserved_cost_ceiling_cny": round(sum(c["reserved_estimate_cny"] or 0 for c in meter.records), 9),
            }
            save(meter.records)
    print(f"Validation finished: {report['status']}; calls={len(meter.records)}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception:  # noqa: BLE001 -- credential/configuration errors must not print a traceback.
        print("Validation stopped safely; check profile, output path and the sanitized report.")
        code = 1
    raise SystemExit(code)

"""M8 synthetic acceptance; dry by default, one cumulative 16-call / CNY .05 ledger."""
import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app
from productivity_agent.api.assistant import config
from productivity_agent.domain.agent_intent import AgentIntent
from productivity_agent.providers.qwen import (
    DEFAULT_BEIJING_BASE_URL,
    DEFAULT_QWEN_MODEL,
    build_qwen_model,
)
from productivity_agent.providers.qwen_meter import QwenMeter, ValidationBudget
from productivity_agent.services.task_store import SQLiteTaskStore
from scripts.validate_qwen_agent import PRICE_SOURCE, checked_profile

CASES = ["A", "B", "C", "D", "E", "F_vague", "F_invalid", "G"]
BUDGET = ValidationBudget(max_calls=16, input_per_call=12000)


def read_ledger(path, profile):
    report = json.loads(path.read_text(encoding="utf-8"))
    calls = report.get("calls", [])
    if (report.get("profile") != profile or report.get("max_calls") != 16
            or report.get("max_cny") != "0.05" or len(calls) >= 16
            or any(c.get("attempt") != i + 1 or type(c.get("input_tokens")) is not int
                   or type(c.get("output_tokens")) is not int for i, c in enumerate(calls))):
        raise ValueError("unsafe_ledger_resume")
    return report


def run_cases(meter, report, root, selected, url):
    now = datetime.fromisoformat(report["reference_now"])
    tomorrow = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    later = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    midnight = (now + timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0)
    tonight = now.replace(hour=23, minute=0, second=0, microsecond=0)
    db = SQLiteTaskStore(root / "business/tasks.sqlite")
    with patch.dict(os.environ, PPA_DATA_DIR=str(root / "agent"), PPA_TASK_SERVICE_URL=url,
                    PPA_ENABLE_LIVE_QWEN="0", LANGSMITH_TRACING="false",
                    LANGCHAIN_TRACING_V2="false"):
        app = create_app(api_token="", session_extractor=meter.structured(AgentIntent))
        with TestClient(app) as api:
            def session():
                return api.post("/v1/assistant/sessions").json()["thread_id"]

            def ask(tid, text, row):
                before = db.list_tasks(limit=1000)
                result = api.post(f"/v1/assistant/sessions/{tid}/messages", json={
                    "message": text, "reference_now": now.isoformat(), "timezone": "Asia/Shanghai",
                    "message_id": str(uuid.uuid4())})
                assert result.status_code == 200
                view = result.json()
                snapshot = api.portal.call(app.state.assistant_graph.aget_state, config(tid))
                row.setdefault("turns", []).append({
                    "input": text, "thread_id": tid, "intent": snapshot.values.get("intent"),
                    "path": (snapshot.values.get("intent") or {}).get("action"),
                    "response": view, "database_before": before,
                    "database_after": db.list_tasks(limit=1000)})
                assert before == db.list_tasks(limit=1000), "write_before_approval"
                return view

            def decide(tid, pending, approved, row):
                before = db.list_tasks(limit=1000)
                assert pending.get("approval"), "expected_approval"
                result = api.post(f"/v1/assistant/sessions/{tid}/decision", json={
                    "operation_id": pending["approval"]["operation_id"], "approved": approved})
                assert result.status_code == 200
                row.setdefault("decisions", []).append({"approved": approved,
                    "approval": pending["approval"], "response": result.json(),
                    "database_before": before, "database_after": db.list_tasks(limit=1000)})
                return result.json()

            def seed(title, due, row):
                task = db.create_task(str(uuid.uuid4()), title, due.isoformat())["task"]
                row.setdefault("synthetic_fixture_setup", []).append(task)
                return task

            for name in selected:
                if meter.stopped or len(meter.records) >= 16:
                    break
                row = {"case": name, "success": False, "calls_before": len(meter.records)}
                report["cases"].append(row)
                meter.scenario = name
                started = time.perf_counter()
                try:
                    tid = session()
                    if name == "B_selection":
                        previous = [c for c in report["cases"][:-1] if c["case"] == "B"
                                    and len(c.get("turns", [])) >= 2][-1]
                        tid = previous["turns"][-1]["thread_id"]
                        row["case"] = "B"
                        row["continuation_from_prior_selection"] = True
                        pending = ask(tid, "明天下午三点的那个。", row)
                        original = next(c for c in report["cases"] if c["case"] == "B" and c.get("decisions"))
                        second = original["decisions"][0]["response"]["result"]["task"]
                        assert pending["approval"]["before"]["id"] == second["id"]
                        assert decide(tid, pending, True, row)["status"] == "updated"
                        assert datetime.fromisoformat(db.get_task(second["id"])["due_at"]) == later
                    elif name == "A":
                        pending = ask(tid, "明天下午三点帮我创建一个准备组会的任务。", row)
                        created = decide(tid, pending, True, row)["result"]["task"]
                        pending = ask(tid, "把准备组会改到后天上午十点。", row)
                        changed = decide(tid, pending, True, row)
                        assert changed["status"] == "updated"
                        task = db.get_task(created["id"])
                        assert datetime.fromisoformat(task["due_at"]) == later
                        assert task["version"] == 2 and len(db.list_tasks()) == 1
                        report["primary_task_id"] = task["id"]
                    elif name == "B":
                        if not report.get("primary_task_id"):
                            raise ValueError("A_dependency_missing")
                        previous = next((c for c in report["cases"][:-1] if c["case"] == "B"
                                         and c.get("decisions")), None)
                        if previous:
                            second = previous["decisions"][0]["response"]["result"]["task"]
                            row["reused_fixture_task_id"] = second["id"]
                        else:
                            pending = ask(tid, "明天下午三点创建一个准备组会的任务。", row)
                            second = decide(tid, pending, True, row)["result"]["task"]
                        pending = ask(tid, "把准备组会改到后天上午十点。", row)
                        assert pending["status"] == "clarification_required" and pending["approval"] is None
                        pending = ask(tid, "明天下午三点的那个。", row)
                        assert pending["approval"]["before"]["id"] == second["id"]
                        changed = decide(tid, pending, True, row)
                        assert changed["status"] == "updated"
                        assert datetime.fromisoformat(db.get_task(second["id"])["due_at"]) == later
                    elif name == "C":
                        existing = [t for t in db.list_tasks() if t["title"] == "午夜合成任务"]
                        task = existing[0] if len(existing) == 1 else seed("午夜合成任务", tonight, row)
                        pending = ask(tid, "把今晚十一点的任务改到明天凌晨一点。", row)
                        assert pending["approval"]["before"]["id"] == task["id"]
                        assert decide(tid, pending, True, row)["status"] == "updated"
                        assert datetime.fromisoformat(db.get_task(task["id"])["due_at"]) == midnight
                    elif name == "D":
                        task = seed("完成合成任务", tomorrow, row)
                        pending = ask(tid, f"请把任务 {task['id']} 标记为已完成。", row)
                        assert decide(tid, pending, True, row)["status"] == "updated"
                        assert db.get_task(task["id"])["status"] == "completed"
                    elif name == "E":
                        task = seed("拒绝合成任务", tomorrow, row)
                        pending = ask(tid, f"把任务 {task['id']} 的标题改为审核材料。", row)
                        assert decide(tid, pending, False, row)["status"] == "cancelled"
                        assert db.get_task(task["id"]) == task
                    elif name.startswith("F"):
                        task = seed("无效时间合成任务", tomorrow, row)
                        text = "把那个任务改一下。" if name == "F_vague" else f"把任务 {task['id']} 改到明天25点。"
                        response = ask(tid, text, row)
                        assert response["status"] == "clarification_required"
                        assert response["approval"] is None
                        assert db.get_task(task["id"]) == task
                    elif name == "G":
                        task_id = report["primary_task_id"]
                        response = ask(tid, f"查询任务 {task_id} 的详情。", row)
                        assert response["result"]["task"] == db.get_task(task_id)
                        assert response["reply"] == json.dumps(db.get_task(task_id), ensure_ascii=False)
                    row["success"] = True
                except Exception as exc:  # noqa: BLE001 -- never serialize SDK exceptions.
                    row["error_category"] = type(exc).__name__
                finally:
                    calls = meter.records[row["calls_before"]:]
                    row.update(model_calls=len(calls), latency_ms=round((time.perf_counter()-started)*1000, 2),
                               database_final=db.list_tasks(limit=1000))
                    meter._save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cases", nargs="+", choices=[*CASES, "B_selection"], default=CASES)
    parser.add_argument("--approved-max-calls", type=int)
    parser.add_argument("--approved-max-cny", type=Decimal)
    parser.add_argument("--out", type=Path, default=Path("reports/task06b/online.json"))
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"live": False, "cases": CASES, "max_calls": 16,
                          "reserved_ceiling_cny": 0.046208, "price_source": PRICE_SOURCE}))
        return 0
    if args.approved_max_calls != 16 or args.approved_max_cny != Decimal("0.05"):
        parser.error("Explicit authorization required: 16 calls / CNY .05")
    logging.disable(logging.CRITICAL)
    load_dotenv(override=False)
    profile = checked_profile(os.getenv("PPA_MODEL", DEFAULT_QWEN_MODEL),
                              os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BEIJING_BASE_URL))
    if not os.getenv("DASHSCOPE_API_KEY", "").strip():
        raise ValueError("credential_missing")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    if args.resume:
        report = read_ledger(args.out, profile)
        directory = root / ".pytest_cache" / report["test_directory"]
        if not directory.resolve().is_relative_to((root / ".pytest_cache").resolve()):
            raise ValueError("unsafe_test_directory")
        if not (directory / "business/tasks.sqlite").exists():
            raise ValueError("isolated_database_missing")
    else:
        directory = Path(tempfile.mkdtemp(prefix="m8-online-", dir=root / ".pytest_cache"))
        report = {"profile": profile, "max_calls": 16, "max_cny": "0.05", "calls": [],
                  "cases": [], "reference_now": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                  "test_directory": directory.name, "actual_billed_cny": None,
                  "pricing_source": PRICE_SOURCE, "price_verified_on": "2026-11-03",
                  "input_cny_per_million": 0.2, "output_cny_per_million": 0.8}
    with args.out.open("r+" if args.resume else "x", encoding="utf-8") as output:
        def save(records):
            report["calls"] = list(records)
            report["totals"] = {"calls": len(records),
                "known_input_tokens": sum(r["input_tokens"] or 0 for r in records),
                "known_output_tokens": sum(r["output_tokens"] or 0 for r in records),
                "unknown_usage_calls": sum(r["input_tokens"] is None for r in records),
                "estimated_cny": round(sum(r["estimated_cny"] or 0 for r in records), 9),
                "reserved_cny": round(sum(r["reserved_estimate_cny"] for r in records), 9)}
            content = json.dumps(report, ensure_ascii=False, indent=2)
            content = content.replace(os.environ["DASHSCOPE_API_KEY"].strip(), "[REDACTED]")
            output.seek(0)
            output.write(content)
            output.truncate()
            output.flush()
            os.fsync(output.fileno())

        meter = QwenMeter(build_qwen_model(), BUDGET, save)
        meter.records = list(report["calls"])
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, PPA_DATA_DIR=str(directory / "business"),
                   PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="")
        with (directory / "service.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn",
                "productivity_agent.api.task_service:create_task_service", "--factory",
                "--host", "127.0.0.1", "--port", str(port)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                url = f"http://127.0.0.1:{port}"
                while True:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("business_service_unavailable")
                    try:
                        if httpx.get(url + "/health", timeout=0.3, trust_env=False).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                run_cases(meter, report, directory, args.cases, url)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                save(meter.records)
    print(json.dumps({"calls": len(meter.records), "cases": [
        {"case": r["case"], "success": r["success"]} for r in report["cases"]]}))
    return 0 if all(r["success"] for r in report["cases"][-len(args.cases):]) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- never expose credentials or SDK tracebacks.
        print("M8 validation stopped safely; inspect the sanitized ledger.")
        raise SystemExit(1) from None

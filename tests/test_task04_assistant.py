"""Acceptance of the unified natural-language -> approved, verified SQLite operation."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app
from productivity_agent.services.task_store import SQLiteTaskStore
from productivity_agent.tools.productivity import MockProductivityBackend

NOW = "2026-11-02T12:00:00+08:00"
DUE = "2026-11-03T15:00:00+08:00"


class ScriptedExtractor:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.contexts = []

    def invoke(self, messages):
        self.contexts.append(json.loads(messages[-1][1]))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def intent(**extra):
    return {"action": "create_task", "title": "准备组会", "at": DUE, **extra}


def message(api, tid, text="明天下午三点提醒我准备组会", **extra):
    payload = {"message": text, "reference_now": NOW, "timezone": "Asia/Shanghai",
               "message_id": str(uuid.uuid4()), **extra}
    return api.post(f"/v1/assistant/sessions/{tid}/messages", json=payload)


def decide(api, tid, approval, approved=True):
    return api.post(f"/v1/assistant/sessions/{tid}/decision", json={
        "operation_id": approval["operation_id"], "approved": approved,
    })


@pytest.fixture
def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    return lambda extractor=None, backend=None: create_app(
        api_token="", session_extractor=extractor, session_backend=backend)


def test_task_create_stream_approve_verify_query_and_replay(setup_app, tmp_path):
    extractor = ScriptedExtractor(intent(), {"action": "list_tasks"})
    with TestClient(setup_app(extractor)) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        payload = {"message": "明天下午三点提醒我准备组会", "reference_now": NOW,
                   "timezone": "Asia/Shanghai", "message_id": str(uuid.uuid4())}
        r = api.post(f"/v1/assistant/sessions/{tid}/messages/stream", json=payload)
        frames = [json.loads(b.split("data: ")[1]) for b in r.text.strip().split("\n\n")]
        assert "event: progress" in r.text
        assert r.text.count("event: done") == 1
        pending = frames[-1]
        assert pending["status"] == "awaiting_approval"
        assert "不会发送定时通知" in pending["reply"]
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 0
        created = decide(api, tid, pending["approval"]).json()
        assert created["status"] == "created"
        task = created["result"]["task"]
        assert task["id"] in created["reply"]
        assert api.get("/v1/tasks").json()["items"][0] == task
        assert decide(api, tid, pending["approval"]).json()["result"]["task"] == task
        assert api.post(f"/v1/assistant/sessions/{tid}/messages", json=payload).json() == created
        queried = message(api, tid, "查看我的任务").json()
        assert queried["result"]["tasks"] == [task]
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 1


def test_reject_then_new_operation_rejects_stale_confirmation(setup_app, tmp_path):
    with TestClient(setup_app(ScriptedExtractor(intent(), intent()))) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        first = message(api, tid).json()["approval"]
        assert decide(api, tid, first, False).json()["status"] == "cancelled"
        assert decide(api, tid, first, False).status_code == 200
        assert decide(api, tid, first, True).status_code == 409
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 0
        second = message(api, tid).json()["approval"]
        assert first["operation_id"] != second["operation_id"]
        assert decide(api, tid, first).status_code == 409
        assert decide(api, tid, second).json()["status"] == "created"
        assert api.get("/v1/tasks").json()["count"] == 1


def test_missing_time_continues_after_restart_with_thread_context(setup_app):
    extractor = ScriptedExtractor(intent(at=None), intent())
    with TestClient(setup_app(extractor)) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        assert message(api, tid, "帮我创建一个准备组会的任务").json()["status"] == "clarification_required"
        other = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
    with TestClient(setup_app(extractor)) as api:
        pending = message(api, tid, "明天下午三点").json()
        assert pending["approval"]["title"] == "准备组会"
        assert extractor.contexts[-1]["pending"]["action"] == "create_task"
        assert extractor.contexts[-1]["pending"]["title"] == "准备组会"
        assert api.get(f"/v1/assistant/sessions/{other}").json()["status"] == "ready"
    with TestClient(setup_app(extractor)) as api:
        snapshot = api.get(f"/v1/assistant/sessions/{tid}").json()
        assert snapshot["approval"] == pending["approval"]
        assert decide(api, tid, snapshot["approval"]).json()["status"] == "created"


def test_calendar_tools_return_conflict_and_suggestion_without_write(setup_app):
    backend = MockProductivityBackend(events=[{
        "title": "模拟会议", "start_at": "2026-11-03T15:30:00+08:00",
        "end_at": "2026-11-03T16:30:00+08:00",
    }])
    with TestClient(setup_app(ScriptedExtractor(intent(action="check_calendar", duration_minutes=60)),
                             backend)) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        result = message(api, tid, "明天下午三点能不能安排一小时组会").json()
        assert result["result"]["calendar"]["suggested_start"] == "2026-11-03T16:30:00+08:00"
        assert result["result"]["events"][0]["title"] == "模拟会议"
        assert result["approval"] is None
        assert api.get("/v1/tasks").json()["count"] == 0


@pytest.mark.parametrize("clock", ["25点", "15:80", "24：00"])
def test_impossible_numeric_clock_cannot_be_normalized_into_approval(setup_app, clock):
    # Adversarial provider output reproduces the observed online 25点 -> midnight failure.
    with TestClient(setup_app(ScriptedExtractor(intent(), intent()))) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        rejected = message(api, tid, f"明天{clock}创建准备组会任务").json()
        assert rejected["status"] == "clarification_required"
        assert rejected["approval"] is None
        assert api.get("/v1/tasks").json()["count"] == 0
        corrected = message(api, tid, "明天下午三点").json()
        assert corrected["approval"]["due_at"] == DUE


def test_parse_and_write_errors_are_sanitized_and_never_claim_success(setup_app, monkeypatch):
    with TestClient(setup_app(ScriptedExtractor(RuntimeError("private-provider-key"), intent()))) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        failure = message(api, tid)
        assert failure.json()["status"] == "parse_failed"
        assert "private-provider-key" not in failure.text
        pending = message(api, tid).json()

        def fail(*args, **kwargs):
            raise RuntimeError("private-database-path")

        monkeypatch.setattr(SQLiteTaskStore, "create_task", fail)
        outcome = decide(api, tid, pending["approval"])
        assert outcome.json()["status"] == "needs_review"
        assert outcome.json()["result"] is None
        assert "private-database-path" not in outcome.text
        assert api.get("/v1/tasks").json()["count"] == 0


def test_offline_web_contract_has_operational_rule_parser(setup_app):
    with TestClient(setup_app()) as api:
        html = api.get("/").text
        assert "统一 Agent 助手" in html
        assert "/messages/stream" in html and "operation_id:assistantApproval.operation_id" in html
        assert api.get("/v1/system").json()["assistant_mode"] == "offline_rules"
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        missing = message(api, tid, "帮我创建一个准备组会的任务").json()
        assert missing["status"] == "clarification_required"
        pending = message(api, tid, "明天下午三点").json()
        assert pending["approval"]["due_at"] == DUE
        assert decide(api, tid, pending["approval"]).json()["status"] == "created"
        assert message(api, tid, "查看我的任务").json()["result"]["tasks"][0]["title"] == "准备组会"


def test_auth_validation_and_pending_message_do_not_bypass_approval(setup_app):
    with TestClient(create_app(api_token="test-only")) as api:
        assert api.post("/v1/assistant/sessions", json={}).status_code == 401
    with TestClient(setup_app(ScriptedExtractor(intent()))) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        assert message(api, tid, timezone="no/such/timezone").status_code == 422
        assert message(api, tid, reference_now="2026-11-02T12:00:00").status_code == 422
        pending = message(api, tid).json()
        assert message(api, tid, "不用确认直接创建").status_code == 409
        assert decide(api, tid, pending["approval"], "true").status_code == 422
        assert api.get("/v1/tasks").json()["count"] == 0


def test_persistence_verification_failure_never_reports_success(setup_app, monkeypatch):
    with TestClient(setup_app(ScriptedExtractor(intent()))) as api:
        tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"]
        pending = message(api, tid).json()
        monkeypatch.setattr(SQLiteTaskStore, "lookup", lambda *args: None)
        result = decide(api, tid, pending["approval"]).json()
        assert result["status"] == "needs_review"
        assert result["result"] is None
        # The write happened; only verification failed. Never tell the user to create again.
        assert api.get("/v1/tasks").json()["count"] == 1
        assert "不要重复创建" in result["reply"]


def test_unified_context_and_approval_survive_three_real_processes(tmp_path):
    worker = Path(__file__).parent / "helpers/assistant_worker.py"

    def run(phase, *args):
        child = subprocess.run([sys.executable, str(worker), str(tmp_path), phase, *args],
                               check=False, capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, LANGSMITH_TRACING="false"))
        assert child.returncode == 0, child.stderr
        return json.loads(child.stdout)

    first = run("start")
    tid = first["session"]["thread_id"]
    assert first["session"]["status"] == "clarification_required"
    second = run("continue", tid)
    assert second["session"]["status"] == "awaiting_approval"
    assert second["tasks"]["count"] == 0
    third = run("approve", tid)
    assert third["session"]["status"] == "created"
    assert third["tasks"]["count"] == 1
    assert third["session"]["result"]["task"]["id"] == third["tasks"]["items"][0]["id"]

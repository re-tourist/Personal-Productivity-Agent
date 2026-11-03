"""Synthetic A-G business acceptance, real sockets and an independent server process."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app
from productivity_agent.services.http_task_store import BusinessUnavailable, HTTPTaskStore
from productivity_agent.services.task_store import (
    AmbiguousCommitError,
    SQLiteTaskStore,
    VersionConflict,
)

NOW = "2026-11-03T12:00:00+08:00"
DUE = "2026-11-04T15:00:00+08:00"


@pytest.fixture
def service(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="",
               LANGSMITH_TRACING="false")
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).parent /
                                   "helpers/business_server.py"), str(tmp_path), str(port)],
                                   env=env, stdout=log, stderr=log)
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, (tmp_path / "server.log").read_text()
                try:
                    if httpx.get(url + "/health", timeout=0.3, trust_env=False).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline
                time.sleep(0.05)
            yield HTTPTaskStore(url), url, tmp_path
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def say(api, tid, text):
    r = api.post(f"/v1/assistant/sessions/{tid}/messages", json={
        "message": text, "reference_now": NOW, "timezone": "Asia/Shanghai",
        "message_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()


def approve(api, tid, pending, decision=True):
    r = api.post(f"/v1/assistant/sessions/{tid}/decision", json={
        "operation_id": pending["approval"]["operation_id"], "approved": decision})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("remote", [False, True])
def test_a_to_f_natural_language_lifecycle(service, monkeypatch, tmp_path, remote):
    store, url, root = service
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path / "agent"))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", url if remote else "")
    store = store if remote else SQLiteTaskStore(tmp_path / "agent/tasks.sqlite")
    with TestClient(create_app(api_token="")) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        pending = say(api, tid, "明天下午三点提醒我准备组会")
        first = approve(api, tid, pending)["result"]["task"]
        pending = say(api, tid, "把准备组会改到后天上午十点")
        assert pending["approval"]["before"]["id"] == first["id"]
        assert pending["approval"]["changes"]["due_at"] == "2026-11-05T10:00:00+08:00"
        changed = approve(api, tid, pending)
        assert changed["status"] == "updated", changed
        assert approve(api, tid, pending) == changed
        assert store.list_tasks()[0]["id"] == first["id"]
        assert len(store.list_tasks()) == 1
        # Same title; selecting the original time must retain the NEW time.
        second = store.create_task(str(uuid.uuid4()), "准备组会", DUE)["task"]
        ambiguous = say(api, tid, "把准备组会改到后天上午十点")
        assert ambiguous["status"] == "clarification_required"
        assert ambiguous["approval"] is None
        assert len(ambiguous["result"]["candidates"]) == 2
        pending = say(api, tid, "明天下午三点的那个")
        assert pending["approval"]["before"]["id"] == second["id"]
        assert pending["approval"]["changes"]["due_at"] == "2026-11-05T10:00:00+08:00"
        before = store.get_task(second["id"])
        assert approve(api, tid, pending, False)["status"] == "cancelled"
        assert store.get_task(second["id"]) == before
        pending = say(api, tid, f"把{second['id']}改到明天凌晨一点")
        result = approve(api, tid, pending)
        assert result["result"]["task"]["due_at"] == "2026-11-03T17:00:00+00:00"
        pending = say(api, tid, f"把{second['id']}改为新标题")
        assert approve(api, tid, pending)["result"]["task"]["title"] == "新标题"
        pending = say(api, tid, f"完成任务 {second['id']}")
        assert approve(api, tid, pending)["result"]["task"]["status"] == "completed"
        detail = say(api, tid, f"查询任务 {second['id']}")
        assert detail["result"]["task"] == store.get_task(second["id"])
        assert len(say(api, tid, "查看我的任务")["result"]["tasks"]) == 2
        # Two independently approved snapshots racing on the same version.
        other = api.post("/v1/assistant/sessions").json()["thread_id"]
        p1 = say(api, tid, f"把{first['id']}改为甲")
        p2 = say(api, other, f"把{first['id']}改为乙")
        assert approve(api, tid, p1)["status"] == "updated"
        assert approve(api, other, p2)["status"] == "conflict"
        assert store.get_task(first["id"])["title"] == "甲"
        assert "修改前" in p1["reply"] and "修改后" in p1["reply"]
    # Independent SQLite read proves the remote service wrote its own durable DB.
    db = root / "tasks.sqlite" if remote else tmp_path / "agent/tasks.sqlite"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
        assert conn.execute("SELECT status FROM tasks WHERE id=?", (second["id"],)).fetchone()[0] == "completed"


def test_g_real_http_faults_and_reconciliation(service):
    store, url, root = service
    task = store.create_task("create", "合成任务", DUE)["task"]
    assert store.lookup("create", "合成任务", DUE)["id"] == task["id"]
    with pytest.raises(KeyError):
        store.get_task("missing")
    with httpx.Client(base_url=url, trust_env=False) as client:
        assert client.post("/tasks", json={}).status_code == 400
        assert client.post("/tasks", json={"operation_id": "x", "title": "x",
                           "due_at": DUE, "approved": False}).status_code == 400
    with pytest.raises(VersionConflict):
        store.change_task("stale", task["id"], 99, "complete_task")
    (root / "fault").write_text("500")
    with pytest.raises(BusinessUnavailable):
        store.change_task("five", task["id"], 1, "complete_task")
    assert store.get_operation("five") is None
    fast = HTTPTaskStore(url, timeout=0.15)
    (root / "fault").write_text("before_timeout")
    with pytest.raises(AmbiguousCommitError):
        fast.change_task("before", task["id"], 1, "complete_task")
    assert store.get_operation("before") is None
    (root / "fault").write_text("after_timeout")
    with pytest.raises(AmbiguousCommitError):
        fast.change_task("after", task["id"], 1, "complete_task")
    op = store.get_operation("after")
    assert op["task"]["version"] == 2
    assert store.get_task(task["id"]) == op["task"]
    replay = store.change_task("after", task["id"], 1, "complete_task")
    assert replay["status"] == "replayed"
    assert store.get_task(task["id"])["version"] == 2


def test_migration_and_simultaneous_writers(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL)")
        conn.execute("INSERT INTO tasks VALUES ('old','legacy',?)", (DUE,))
    store = SQLiteTaskStore(path)
    assert SQLiteTaskStore(path).get_task("old")["version"] == 1

    def write(op):
        try:
            return store.change_task(op, "old", 1, "update_task", title=op)["status"]
        except VersionConflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(write, ["one", "two"])) == ["conflict", "updated"]
    assert store.get_task("old")["version"] == 2


@pytest.mark.parametrize("fault,expected", [("500", "needs_review"),
                                         ("before_timeout", "needs_review"),
                                         ("after_timeout", "updated")])
def test_agent_reconciles_real_http_failure(service, monkeypatch, caplog, fault, expected):
    store, url, root = service
    monkeypatch.setenv("PPA_DATA_DIR", str(root / "agent"))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", url)
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    original = HTTPTaskStore.__init__

    def fast(self, base_url):
        original(self, base_url, timeout=0.15)

    monkeypatch.setattr(HTTPTaskStore, "__init__", fast)
    task = store.create_task("seed", "故障测试", DUE)["task"]
    caplog.set_level("INFO", logger="ppa.http")
    caplog.set_level("INFO", logger="ppa.agent")
    with TestClient(create_app(api_token="")) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        pending = say(api, tid, f"把{task['id']}改为故障后标题")
        (root / "fault").write_text(fault)
        result = approve(api, tid, pending)
        assert result["status"] == expected, result
        current = store.get_task(task["id"])
        assert current["version"] == (2 if expected == "updated" else 1)
        assert approve(api, tid, pending) == result
        assert store.get_task(task["id"]) == current
    records = [json.loads(r.message) for r in caplog.records if r.name == "ppa.http"]
    writes = [r for r in records if r["http_action"] == "PATCH"]
    assert len(writes) == 1
    assert writes[0]["thread_id"] == tid
    assert writes[0]["operation_id"] == pending["approval"]["operation_id"]
    assert writes[0]["target_id"] == task["id"]
    assert "故障后标题" not in "".join(r.message for r in caplog.records if r.name.startswith("ppa."))


def test_update_clarification_restart_and_midnight(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    with TestClient(create_app(api_token="")) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        task = approve(api, tid, say(api, tid, "今晚十一点提醒我跨日任务"))["result"]["task"]
        assert task["due_at"] == "2026-11-03T15:00:00+00:00"
        assert say(api, tid, f"把{task['id']}改到稍后")["status"] == "clarification_required"
    with TestClient(create_app(api_token="")) as api:
        pending = say(api, tid, "明天凌晨一点")
        assert pending["approval"]["before"]["id"] == task["id"]
    with TestClient(create_app(api_token="")) as api:
        assert approve(api, tid, pending)["result"]["task"]["due_at"] == "2026-11-03T17:00:00+00:00"

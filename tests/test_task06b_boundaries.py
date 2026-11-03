"""Evidence for legacy operation preservation, immutable replay and validation budget."""
import json
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from test_task06_operations import approve, say

from productivity_agent.api.app import create_app
from productivity_agent.services.task_store import (
    IdempotencyConflict,
    SQLiteTaskStore,
    VersionConflict,
    request_fingerprint,
)
from scripts.validate_m8_qwen import BUDGET, read_ledger

DUE = "2026-11-04T07:00:00+00:00"


def test_migration_preserves_historical_operation_and_replay(tmp_path):
    path = tmp_path / "legacy.sqlite"
    digest = request_fingerprint("legacy", DUE)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL);
            CREATE TABLE task_operations(operation_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(id));
        """)
        conn.execute("INSERT INTO tasks VALUES ('old','legacy',?)", (DUE,))
        conn.execute("INSERT INTO task_operations VALUES ('historic',?,'old')", (digest,))
    for _ in range(2):
        store = SQLiteTaskStore(path)
        assert store.lookup("historic", "legacy", DUE)["id"] == "old"
        assert store.create_task("historic", "legacy", DUE)["status"] == "replayed"
        assert store.count_tasks() == 1
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT * FROM task_operations").fetchall() == [
                ("historic", digest, "old")]
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(IdempotencyConflict):
        store.change_task("historic", "old", 1, "complete_task")


def test_replay_old_result_never_overwrites_later_state(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    task = store.create_task("create", "original", DUE)["task"]
    first = store.change_task("first", task["id"], 1, "update_task", title="first")
    store.change_task("second", task["id"], 2, "complete_task")
    assert store.change_task("first", task["id"], 1, "update_task", title="first")["task"] == first["task"]
    assert store.get_task(task["id"])["version"] == 3
    assert store.get_task(task["id"])["status"] == "completed"
    with pytest.raises(VersionConflict):
        store.change_task("stale", task["id"], 1, "update_task", title="overwrite")
    with pytest.raises(IdempotencyConflict):
        store.create_task("first", "other", DUE)
    with pytest.raises(IdempotencyConflict):
        store.change_task("first", task["id"], 1, "update_task", title="other")


def test_m8_validation_dry_and_resume_budget(tmp_path):
    run = subprocess.run([sys.executable, "-m", "scripts.validate_m8_qwen"],
                         capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(run.stdout)["live"] is False
    reserve = BUDGET.max_calls * (BUDGET.input_per_call * 0.2 + BUDGET.output_reserve * 0.8) / 1e6
    assert reserve <= 0.05 and BUDGET.max_calls == 16
    profile = {"model": "qwen3.7-flash", "region": "cn-beijing", "endpoint": "workspace"}
    report = {"max_calls": 16, "max_cny": "0.05", "profile": profile, "calls": [
        {"attempt": 1, "input_tokens": 1200, "output_tokens": 80}]}
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert len(read_ledger(path, profile)["calls"]) == 1
    report["calls"][0]["input_tokens"] = None
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        read_ledger(path, profile)


class Extractor:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)

    def invoke(self, messages):
        return next(self.outputs)


@pytest.mark.parametrize("inferred_id", [False, True])
@pytest.mark.parametrize("missing_patch", [False, True])
def test_historical_selector_cannot_bypass_ambiguity(tmp_path, monkeypatch, inferred_id, missing_patch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    first = store.create_task("first", "同名", DUE)["task"]
    second = store.create_task("second", "同名", "2026-11-05T10:00:00+08:00")["task"]
    request = {"action": "update_task", "title": "同名", "at": "2026-11-06T10:00:00+08:00",
               "new_time_text": "大后天十点", "target_at": DUE,
               "task_id": first["id"] if inferred_id else None}
    if missing_patch:
        request["at"] = None
    # Replay observed hallucinated original time; then a selection which wrongly changes the patch.
    selected = {**request, "task_id": None,
                "at": "2026-11-06T10:00:00+08:00" if missing_patch else DUE,
                "target_time_text": "明天下午三点", "question": "请提供具体ID"}
    with TestClient(create_app(api_token="", session_extractor=Extractor(request, selected))) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        pending = say(api, tid, "把同名任务改到大后天十点")
        assert pending["status"] == "clarification_required"
        assert pending["approval"] is None
        assert len(pending["result"]["candidates"]) == 2
        pending = say(api, tid, "明天下午三点的那个")
        assert pending["approval"]["before"]["id"] == first["id"]
        assert pending["approval"]["changes"]["due_at"] == "2026-11-06T10:00:00+08:00"
        assert approve(api, tid, pending)["status"] == "updated"
        assert store.get_task(second["id"]) == second


def test_time_only_selector_requires_grounded_quote(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    task = store.create_task("seed", "时间定位", "2026-11-03T23:00:00+08:00")["task"]
    output = {"action": "update_task", "target_at": "2026-11-03T23:00:00+08:00",
              "at": "2026-11-04T01:00:00+08:00", "target_time_text": "今晚十一点",
              "new_time_text": "明天凌晨一点", "question": "请提供具体标题"}
    with TestClient(create_app(api_token="", session_extractor=Extractor(output))) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        pending = say(api, tid, "把今晚十一点的任务改到明天凌晨一点")
        assert pending["approval"]["before"]["id"] == task["id"]
        assert approve(api, tid, pending)["result"]["task"]["due_at"] == "2026-11-03T17:00:00+00:00"

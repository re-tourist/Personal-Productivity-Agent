"""Optional REAL LangGraph M6 integration tests (zero live Qwen calls).

Requires full project overlay M1-M5, langgraph-checkpoint-sqlite, aiosqlite.
"""

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("langgraph")
pytest.importorskip("langgraph.checkpoint.sqlite.aio")

from productivity_agent.api.app import create_app
from productivity_agent.services.task_store import SQLiteTaskStore


def test_root_redirects_to_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    with TestClient(create_app(api_token="")) as api:
        redirect = api.get("/", follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers["location"] == "/app"
        page = api.get("/")
        assert page.status_code == 200
        assert page.url.path == "/app"
        assert page.headers["content-type"].startswith("text/html")
        assert "Personal Productivity Agent" in page.text
        assert "日程冲突检查" in page.text
        assert api.get("/health").status_code == 200
        assert api.get("/docs").status_code == 200
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 0


def test_real_approval_survives_service_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    with TestClient(create_app(api_token="")) as api:
        response = api.post("/v1/tasks/drafts", json={
            "title": "准备组会", "due_at": "2026-12-10T15:00:00+08:00"
        })
        assert response.status_code == 201, response.text
        tid = response.json()["thread_id"]
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 0

    with TestClient(create_app(api_token="")) as api:
        state = api.get(f"/v1/tasks/drafts/{tid}")
        assert state.status_code == 200, state.text
        assert state.json()["status"] == "awaiting_approval"
        decision = api.post(
            f"/v1/tasks/drafts/{tid}/decision", json={"approved": True}
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["status"] in {"created", "recovered"}
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 1

    with TestClient(create_app(api_token="")) as api:
        state = api.get(f"/v1/tasks/drafts/{tid}")
        assert state.json()["status"] in {"created", "recovered"}
        assert api.post(f"/v1/tasks/drafts/{tid}/decision", json={"approved": True}).status_code == 409
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 1


def test_real_calendar_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    with TestClient(create_app(api_token="")) as api:
        payload = {
            "request": {
                "title": "组会",
                "start_at": "2026-11-03T15:00:00+08:00",
                "end_at": "2026-11-03T16:00:00+08:00",
            },
            "busy_slots": [{
                "start_at": "2026-11-03T15:30:00+08:00",
                "end_at": "2026-11-03T16:30:00+08:00",
            }],
        }
        check = api.post("/v1/calendar/check", json=payload)
        assert check.status_code == 200, check.text
        assert check.json()["result"]["suggested_start"] == "2026-11-03T16:30:00+08:00"
        stream = api.post("/v1/calendar/check/stream", json=payload)
        assert stream.status_code == 200
        assert "event: progress" in stream.text
        assert "event: done" in stream.text

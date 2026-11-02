"""M7 HTTP and dashboard contract tests: no real LLM or LangGraph required."""

from pathlib import Path

from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app
from productivity_agent.services.task_store import SQLiteTaskStore


class FakeIntentGraph:
    def __init__(self):
        self.payload = None

    async def ainvoke(self, payload):
        self.payload = payload
        return {
            "result": {"status": "clarification_required", "message": "请问几点开始？"},
            "parsed_intent": {"action": "schedule_event", "start_at": None},
        }


class DisabledGraph:
    """This test only exercises M7 endpoints that do not invoke legacy graphs."""


def client(tmp_path, *, token="", extractor=None):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    return TestClient(create_app(
        approval_graph=DisabledGraph(), calendar_graph=DisabledGraph(),
        store=store, intent_graph=extractor, api_token=token,
    ))


def test_dashboard_is_real_static_page(tmp_path):
    with client(tmp_path) as api:
        response = api.get("/app")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Personal Productivity Agent" in response.text
        assert "Qwen Tool Agent" in response.text
        assert "日程冲突检查" in response.text


def test_system_and_local_task_list(tmp_path):
    with client(tmp_path) as api:
        sys = api.get("/v1/system").json()
        assert sys["version"] == "1.0.0"
        assert sys["live_qwen_enabled"] is False
        store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
        store.create_task("task-op-001", "准备组会", "2026-12-10T15:00:00+08:00")
        output = api.get("/v1/tasks").json()
        assert output["count"] == 1
        assert output["items"][0]["title"] == "准备组会"
        assert api.get("/v1/tasks?limit=0").status_code == 422


def test_m7_endpoints_enforce_token_when_set(tmp_path):
    with client(tmp_path, token="local-key") as api:
        assert api.get("/v1/tasks").status_code == 401
        assert api.get("/v1/system").status_code == 401
        assert api.get("/v1/tasks", headers={"X-PPA-Token": "local-key"}).status_code == 200


def test_natural_language_disabled_without_key(tmp_path):
    with client(tmp_path) as api:
        output = api.post("/v1/calendar/natural-language", json={
            "message": "明天下午三点安排组会",
            "reference_now": "2026-11-02T16:00:00+08:00",
        })
        assert output.status_code == 503


def test_natural_language_uses_existing_m2_graph(tmp_path):
    fake = FakeIntentGraph()
    with client(tmp_path, extractor=fake) as api:
        response = api.post("/v1/calendar/natural-language", json={
            "message": "明天下午安排组会",
            "reference_now": "2026-11-02T16:00:00+08:00",
            "busy_slots": [{
                "start_at": "2026-11-03T15:00:00+08:00",
                "end_at": "2026-11-03T16:00:00+08:00",
            }],
        })
        assert response.status_code == 200, response.text
        assert response.json()["result"]["status"] == "clarification_required"
        assert fake.payload["user_text"] == "明天下午安排组会"
        assert len(fake.payload["busy_slots"]) == 1


def test_natural_language_rejects_naive_reference_time(tmp_path):
    with client(tmp_path, extractor=FakeIntentGraph()) as api:
        response = api.post("/v1/calendar/natural-language", json={
            "message": "开组会", "reference_now": "2026-11-02T16:00:00",
        })
        assert response.status_code == 422

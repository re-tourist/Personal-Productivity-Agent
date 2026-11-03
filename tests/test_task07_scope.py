"""No live calls: replay adversarial online selectors at the safety boundary."""
import pytest
from fastapi.testclient import TestClient
from test_task06_operations import approve, say

from productivity_agent.api.app import create_app
from productivity_agent.services.task_store import SQLiteTaskStore


class OnlineReplay:
    mode = "qwen"

    def __init__(self, output):
        self.output = output

    def invoke(self, messages):
        return self.output


@pytest.mark.parametrize("kind", ["duplicate", "time_only", "invented_title", "invalid_clock"])
def test_uncertain_online_target_never_enters_approval(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    store.create_task("one", "同名", "2026-11-04T15:00:00+08:00")
    if kind == "duplicate":
        store.create_task("two", "同名", "2026-11-05T15:00:00+08:00")
    before = store.list_tasks()
    output = {"action": "update_task", "title": "同名", "at": "2026-11-05T10:00:00+08:00",
              "target_at": "2026-11-04T15:00:00+08:00", "target_time_text": "明天下午三点"}
    text = "把同名改到后天上午十点，明天下午三点的那个"
    if kind == "time_only":
        output["title"] = None
        text = "把明天下午三点的任务改到后天上午十点"
    elif kind == "invented_title":
        text = "把那个任务改到后天上午十点"
    elif kind == "invalid_clock":
        text = "把同名改到明天25点"
    with TestClient(create_app(api_token="", session_extractor=OnlineReplay(output))) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        result = say(api, tid, text)
        assert result["status"] == "clarification_required"
        assert result["approval"] is None
        assert store.list_tasks() == before


def test_explicit_id_still_works_in_online_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    task = store.create_task("seed", "目标", "2026-11-04T15:00:00+08:00")["task"]
    output = {"action": "complete_task", "task_id": task["id"]}
    with TestClient(create_app(api_token="", session_extractor=OnlineReplay(output))) as api:
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        pending = say(api, tid, f"完成任务 {task['id']}")
        assert approve(api, tid, pending)["result"]["task"]["status"] == "completed"

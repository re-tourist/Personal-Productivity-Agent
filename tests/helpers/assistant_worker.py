"""Real OS-process acceptance for the unified offline conversation and approval graph."""
import json
import os
import sys
import uuid

from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app

os.environ["PPA_DATA_DIR"] = sys.argv[1]
os.environ["PPA_ENABLE_LIVE_QWEN"] = "0"
os.environ["DASHSCOPE_API_KEY"] = ""
phase = sys.argv[2]
with TestClient(create_app(api_token="")) as api:
    tid = api.post("/v1/assistant/sessions", json={}).json()["thread_id"] if phase == "start" else sys.argv[3]
    if phase in {"start", "continue"}:
        result = api.post(f"/v1/assistant/sessions/{tid}/messages", json={
            "message": "帮我创建一个准备组会的任务" if phase == "start" else "明天下午三点",
            "reference_now": "2026-11-02T12:00:00+08:00", "timezone": "Asia/Shanghai",
            "message_id": str(uuid.uuid4()),
        })
    else:
        snapshot = api.get(f"/v1/assistant/sessions/{tid}").json()
        result = api.post(f"/v1/assistant/sessions/{tid}/decision", json={
            "operation_id": snapshot["approval"]["operation_id"], "approved": True,
        })
    assert result.status_code == 200, result.text
    print(json.dumps({"session": result.json(), "tasks": api.get("/v1/tasks").json()}))

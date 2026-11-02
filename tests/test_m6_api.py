"""M6 transport-layer offline tests; fake graphs avoid LLM and LangGraph installation."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app


class FakeCalendarGraph:
    def __init__(self):
        self.called = 0

    async def ainvoke(self, state):
        self.called += 1
        return {"result": {"status": "available", "title": state["request"]["title"]}}

    async def astream(self, state, stream_mode):
        assert stream_mode == "updates"
        yield {"validate_request": {"error": None}}
        yield {"mark_available": {"result": {"status": "available"}}}


class FakeApprovalGraph:
    def __init__(self):
        self.threads = {}

    async def ainvoke(self, payload, config):
        tid = config["configurable"]["thread_id"]
        if isinstance(payload, dict):
            self.threads[tid] = {**payload, "status": "awaiting_approval"}
            return {"__interrupt__": [SimpleNamespace(value={"question": "确认创建？", "title": payload["title"]})]}
        approved = payload.resume
        state = self.threads[tid]
        state["status"] = "created" if approved else "cancelled"
        state["task"] = {"id": "task-mock-1"} if approved else None
        return dict(state)

    async def aget_state(self, config):
        tid = config["configurable"]["thread_id"]
        state = self.threads.get(tid, {})
        nxt = ("approval",) if state.get("status") == "awaiting_approval" else ()
        return SimpleNamespace(values=dict(state), next=nxt)


class FakeAgentGraph:
    async def ainvoke(self, state):
        return {"messages": [SimpleNamespace(content="这是模拟的千问回答")], "llm_calls": 1}

    async def astream(self, state, stream_mode):
        yield {"agent": {"messages": [SimpleNamespace(content="这是模拟的千问回答")]}}


def client(*, token="", live=False):
    return TestClient(create_app(
        approval_graph=FakeApprovalGraph(), calendar_graph=FakeCalendarGraph(),
        store=object(), live_agent=FakeAgentGraph() if live else None, api_token=token,
        command_factory=lambda approved: SimpleNamespace(resume=approved),
    ))


CALENDAR = {"request": {"title": "组会", "start_at": "2026-11-03T15:00:00+08:00", "end_at": "2026-11-03T16:00:00+08:00"}, "busy_slots": []}
TASK = {"title": "准备组会", "due_at": "2026-11-03T15:00:00+08:00"}


def test_health():
    with client() as c:
        assert c.get("/health").json()["status"] == "ok"


def test_check_calendar_and_sse():
    with client() as c:
        assert c.post("/v1/calendar/check", json=CALENDAR).json()["result"]["status"] == "available"
        r = c.post("/v1/calendar/check/stream", json=CALENDAR)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "event: progress" in r.text
        assert '"status": "available"' in r.text
        assert "event: done" in r.text


def test_validation_rejects_naive_datetime_and_extra_fields():
    with client() as c:
        invalid = {"request": {**CALENDAR["request"], "start_at": "2026-11-03T15:00:00"}, "busy_slots": []}
        assert c.post("/v1/calendar/check", json=invalid).status_code == 422
        assert c.post("/v1/tasks/drafts", json={**TASK, "unexpected": 1}).status_code == 422
        assert c.post("/v1/tasks/drafts", json={"title": "   ", "due_at": TASK["due_at"]}).status_code == 422


def test_start_status_approve_and_duplicate_decision():
    with client() as c:
        response = c.post("/v1/tasks/drafts", json=TASK)
        assert response.status_code == 201
        tid = response.json()["thread_id"]
        assert response.json()["status"] == "awaiting_approval"
        assert c.get(f"/v1/tasks/drafts/{tid}").json()["status"] == "awaiting_approval"
        accepted = c.post(f"/v1/tasks/drafts/{tid}/decision", json={"approved": True})
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "created"
        assert c.get(f"/v1/tasks/drafts/{tid}").json()["status"] == "created"
        assert c.post(f"/v1/tasks/drafts/{tid}/decision", json={"approved": True}).status_code == 409


def test_cancel_and_unknown_thread():
    with client() as c:
        tid = c.post("/v1/tasks/drafts", json=TASK).json()["thread_id"]
        assert c.post(f"/v1/tasks/drafts/{tid}/decision", json={"approved": False}).json()["status"] == "cancelled"
        assert c.get("/v1/tasks/drafts/missing").status_code == 404
        assert c.post("/v1/tasks/drafts/missing/decision", json={"approved": True}).status_code == 404


def test_optional_token_protects_endpoints():
    with client(token="test-secret") as c:
        assert c.post("/v1/tasks/drafts", json=TASK).status_code == 401
        assert c.post("/v1/tasks/drafts", json=TASK, headers={"X-PPA-Token": "wrong"}).status_code == 401
        assert c.post("/v1/tasks/drafts", json=TASK, headers={"X-PPA-Token": "test-secret"}).status_code == 201


def test_live_agent_disabled_by_default():
    with client() as c:
        r = c.post("/v1/agent/ask", json={"message": "你好", "reference_now": "2026-11-02T15:00:00+08:00"})
        assert r.status_code == 503


def test_fake_live_agent_and_stream():
    payload = {"message": "你好", "reference_now": "2026-11-02T15:00:00+08:00"}
    with client(live=True) as c:
        assert c.post("/v1/agent/ask", json=payload).json()["model_calls"] == 1
        r = c.post("/v1/agent/stream", json=payload)
        assert r.status_code == 200
        assert "event: progress" in r.text
        assert "event: done" in r.text

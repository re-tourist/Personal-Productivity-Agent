"""M7 HTTP adapter integrating PPA M1-M5 and an optional Qwen intent graph.

Local demo only: SQLite, one Uvicorn worker, loopback binding, and optional demo token.
No live Qwen calls unless PPA_ENABLE_LIVE_QWEN=1; no real task/calendar writes.

Run:
    uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from productivity_agent.api.resources import resources_for
from productivity_agent.services.identity import (
    ThreadOwnership,
    authorize_thread,
    claim_thread,
    identity_for,
    install_identity,
    thread_key,
)


def _encode_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarSlot(StrictModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def _valid_interval(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CalendarRequestBody(CalendarSlot):
    title: str = Field(min_length=1, max_length=200)


class CalendarCheckRequest(StrictModel):
    request: CalendarRequestBody
    busy_slots: list[CalendarSlot] = Field(default_factory=list, max_length=1000)

    def to_graph_input(self) -> dict:
        return {
            "request": {
                "title": self.request.title,
                "start_at": self.request.start_at.isoformat(),
                "end_at": self.request.end_at.isoformat(),
            },
            "busy_slots": [
                {"start_at": x.start_at.isoformat(), "end_at": x.end_at.isoformat()}
                for x in self.busy_slots
            ],
        }


class NaturalLanguageCalendarRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    reference_now: AwareDatetime
    busy_slots: list[CalendarSlot] = Field(default_factory=list, max_length=1000)


class TaskDraftRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime

    @field_validator("title")
    @classmethod
    def _no_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return value.strip()


class DecisionRequest(StrictModel):
    approved: bool


class AgentQueryRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    reference_now: AwareDatetime


def _snapshot_response(thread_id: str, snapshot: Any) -> dict:
    state = dict(snapshot.values or {})
    if not state:
        raise HTTPException(status_code=404, detail="unknown thread_id")
    if "approval" in (snapshot.next or ()):
        status = "awaiting_approval"
    else:
        status = state.get("status", "unknown")
    # Do not return the full checkpoint: internal fields must stay internal.
    return {
        "thread_id": thread_id,
        "status": status,
        "title": state.get("title"),
        "due_at": state.get("due_at"),
        "task": state.get("task"),
        "error": state.get("error"),
    }


def _check_token(request: Request) -> None:
    """Optional demo token. Authentication and ownership require a real provider in prod."""
    if request.app.state.accounts.enabled:
        identity_for(request)  # Middleware already verified the credential.
        return
    expected = getattr(request.app.state, "api_token", "")
    if expected and not secrets.compare_digest(
        request.headers.get("X-PPA-Token", ""), expected
    ):
        raise HTTPException(status_code=401, detail="invalid or missing X-PPA-Token")


def create_app(
    *,
    approval_graph: Any = None,
    calendar_graph: Any = None,
    store: Any = None,
    live_agent: Any = None,
    intent_graph: Any = None,
    api_token: str | None = None,
    command_factory: Any = None,
    session_extractor: Any = None,
    session_backend: Any = None,
) -> FastAPI:
    """Create an app. Inject fake graphs/stores for offline HTTP tests.

    In normal mode resources are opened during lifespan, not import time.
    A single process is required: per-thread locks are in-process only.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from productivity_agent.services.operation_trace import configure_logging
        configure_logging()
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
        except ImportError:
            pass  # The installed project declares python-dotenv as a dependency.
        app.state.api_token = (
            os.getenv("PPA_API_TOKEN", "") if api_token is None else api_token
        )
        app.state.accounts = type(app.state.accounts)(os.getenv("PPA_AUTH_CONFIG"))
        app.state.thread_locks = {}
        app.state.live_agent = live_agent
        app.state.intent_graph = intent_graph
        app.state.command_factory = command_factory
        app.state.assistant_graph = None
        app.state.assistant_mode = "unavailable"
        if approval_graph is not None:
            app.state.approval_graph = approval_graph
            app.state.calendar_graph = calendar_graph
            app.state.store = store
            yield
            return

        # Defer these imports: unit tests of the transport layer don't need LangGraph.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from productivity_agent.domain.agent_intent import AgentIntent
        from productivity_agent.providers.offline_intent import OfflineIntentExtractor
        from productivity_agent.services.task_store import SQLiteTaskStore
        from productivity_agent.tools.productivity import MockProductivityBackend
        from productivity_agent.workflows.approval_session import build_approval_graph
        from productivity_agent.workflows.assistant import build_assistant_graph
        from productivity_agent.workflows.calendar import build_graph

        data_dir = Path(os.getenv("PPA_DATA_DIR", ".ppa-data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        app.state.thread_ownership = ThreadOwnership(data_dir / "access.sqlite")
        task_store = SQLiteTaskStore(data_dir / "tasks.sqlite")
        if os.getenv("PPA_TASK_SERVICE_URL"):
            from productivity_agent.services.http_task_store import HTTPTaskStore
            task_store = HTTPTaskStore(os.environ["PPA_TASK_SERVICE_URL"])
        async with AsyncSqliteSaver.from_conn_string(
            str(data_dir / "m6-checkpoints.sqlite")
        ) as saver:
            app.state.approval_graph = build_approval_graph(task_store, saver)
            app.state.calendar_graph = build_graph()
            app.state.store = task_store
            extractor = session_extractor or OfflineIntentExtractor()
            app.state.assistant_mode = (
                getattr(session_extractor, "mode", "scripted") if session_extractor else "offline_rules"
            )
            if os.getenv("PPA_ENABLE_LIVE_QWEN", "0") == "1":
                from productivity_agent.domain.intent import ScheduleIntent
                from productivity_agent.providers.qwen import build_qwen_model
                from productivity_agent.providers.qwen_meter import QwenMeter
                from productivity_agent.tools.productivity import MockProductivityBackend
                from productivity_agent.workflows.natural_language import (
                    build_natural_language_graph,
                )
                from productivity_agent.workflows.tool_agent import build_tool_agent

                model = build_qwen_model()
                app.state.live_agent = build_tool_agent(
                    model, MockProductivityBackend(),
                    allow_mock_writes=False, max_model_calls=4,
                )
                app.state.intent_graph = build_natural_language_graph(
                    model.with_structured_output(ScheduleIntent, method="function_calling")
                )
                if session_extractor is None:
                    extractor = QwenMeter(model).structured(AgentIntent)
                    app.state.assistant_mode = "qwen"
            if session_backend is None:
                from productivity_agent.demo_data import make_tomorrow_conflict_case
                sample = make_tomorrow_conflict_case()
                backend = MockProductivityBackend(events=[{
                    "title": "模拟已有组会", **sample["busy_slots"][0],
                }])
            else:
                backend = session_backend
            app.state.saver = saver
            app.state.session_extractor = extractor
            app.state.session_backend = backend
            app.state.assistant_graph = build_assistant_graph(extractor, task_store, saver, backend)
            yield

    app = FastAPI(
        title="Personal Productivity Agent", version="1.0.0", lifespan=lifespan
    )
    install_identity(app)
    from productivity_agent.api.assistant import assistant_router
    app.include_router(assistant_router(_check_token))

    @app.get("/", include_in_schema=False)
    async def home():
        return RedirectResponse(url="/app", status_code=307)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "personal-productivity-agent", "version": "1.0.0"}

    @app.get("/app", include_in_schema=False)
    async def dashboard():
        path = Path(__file__).resolve().parents[1] / "static" / "index.html"
        return FileResponse(path, media_type="text/html")

    @app.get("/v1/system", dependencies=[Depends(_check_token)])
    async def system(request: Request) -> dict:
        return {
            "version": "1.0.0",
            "live_qwen_enabled": request.app.state.live_agent is not None,
            "intent_parser_enabled": request.app.state.intent_graph is not None,
            "assistant_mode": request.app.state.assistant_mode,
            "storage": "SQLite demo; local single-process",
            "auth_enabled": request.app.state.accounts.enabled,
            "warning": "Local test authentication; bind only to 127.0.0.1" if request.app.state.accounts.enabled else "No user-scoped authentication; bind only to 127.0.0.1",
        }

    @app.get("/v1/me", dependencies=[Depends(_check_token)])
    async def me(request: Request):
        return {"owner_id": identity_for(request).owner_id, "auth_enabled": request.app.state.accounts.enabled}

    @app.get("/v1/tasks", dependencies=[Depends(_check_token)])
    async def list_tasks(request: Request, limit: int = 100) -> dict:
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be 1..100")
        # SQLiteTaskStore is synchronous; avoid blocking the event loop.
        records = await asyncio.to_thread(resources_for(request).store.list_tasks, limit=limit)
        return {"items": records, "count": len(records)}

    @app.get("/v1/tasks/{task_id}", dependencies=[Depends(_check_token)])
    async def task_detail(task_id: str, request: Request):
        try:
            return await asyncio.to_thread(resources_for(request).store.get_task, task_id)
        except KeyError:
            raise HTTPException(404, "resource_not_found") from None

    @app.get("/v1/operations/{operation_id}", dependencies=[Depends(_check_token)])
    async def operation_detail(operation_id: str, request: Request):
        result = await asyncio.to_thread(resources_for(request).store.get_operation, operation_id)
        if result is None:
            raise HTTPException(404, "resource_not_found")
        return {"operation": result}

    @app.post("/v1/calendar/natural-language", dependencies=[Depends(_check_token)])
    async def calendar_natural_language(body: NaturalLanguageCalendarRequest, request: Request) -> dict:
        graph = request.app.state.intent_graph
        if graph is None:
            raise HTTPException(status_code=503, detail="Qwen intent parser disabled; set PPA_ENABLE_LIVE_QWEN=1")
        try:
            outcome = await graph.ainvoke({
                "user_text": body.message,
                "reference_now": body.reference_now.isoformat(),
                "busy_slots": [
                    {"start_at": s.start_at.isoformat(), "end_at": s.end_at.isoformat()}
                    for s in body.busy_slots
                ],
            })
        except Exception as exc:
            # Do not leak API keys or provider-specific internal error messages.
            raise HTTPException(status_code=502, detail="Intent parsing failed") from exc
        return {"result": outcome["result"], "parsed_intent": outcome.get("parsed_intent")}

    @app.post("/v1/calendar/check", dependencies=[Depends(_check_token)])
    async def calendar_check(body: CalendarCheckRequest, request: Request) -> dict:
        outcome = await request.app.state.calendar_graph.ainvoke(body.to_graph_input())
        return {"result": outcome["result"]}

    @app.post("/v1/calendar/check/stream", dependencies=[Depends(_check_token)])
    async def calendar_check_stream(body: CalendarCheckRequest, request: Request):
        graph = request.app.state.calendar_graph

        async def events() -> AsyncIterator[str]:
            final = None
            try:
                async for update in graph.astream(
                    body.to_graph_input(), stream_mode="updates"
                ):
                    for node, patch in update.items():
                        yield _encode_sse("progress", {"node": node, "status": "completed"})
                        if isinstance(patch, dict) and "result" in patch:
                            final = patch["result"]
                yield _encode_sse("done", {"result": final})
            except Exception:  # noqa: BLE001 -- SSE boundary returns a sanitized terminal error.
                # Headers have already been sent; do not leak exceptions or claim success.
                yield _encode_sse("error", {"message": "calendar workflow failed"})

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/tasks/drafts", status_code=201, dependencies=[Depends(_check_token)])
    async def create_task_draft(body: TaskDraftRequest, request: Request) -> dict:
        thread_id, operation_id = str(uuid.uuid4()), str(uuid.uuid4())
        claim_thread(request, "draft", thread_id)
        config = _thread_config(thread_key(request, "draft", thread_id))
        graph = resources_for(request).approval_graph
        outcome = await graph.ainvoke({
            "owner_id": identity_for(request).owner_id,
            "operation_id": operation_id,
            "title": body.title,
            "due_at": body.due_at.isoformat(),
        }, config=config)
        if "__interrupt__" not in outcome:
            # A validation error in the existing M5 graph.
            raise HTTPException(status_code=422, detail=outcome.get("error", "invalid task"))
        return {
            "thread_id": thread_id,
            "status": "awaiting_approval",
            "approval": outcome["__interrupt__"][0].value,
        }

    @app.get("/v1/tasks/drafts/{thread_id}", dependencies=[Depends(_check_token)])
    async def get_task_draft(thread_id: str, request: Request) -> dict:
        authorize_thread(request, "draft", thread_id)
        snapshot = await resources_for(request).approval_graph.aget_state(_thread_config(thread_key(request, "draft", thread_id)))
        return _snapshot_response(thread_id, snapshot)

    @app.post("/v1/tasks/drafts/{thread_id}/decision", dependencies=[Depends(_check_token)])
    async def decide_task_draft(
        thread_id: str, body: DecisionRequest, request: Request
    ) -> dict:
        factory = request.app.state.command_factory
        if factory is None:
            from langgraph.types import Command
            factory = lambda decision: Command(resume=decision)

        authorize_thread(request, "draft", thread_id)
        graph = resources_for(request).approval_graph
        # Protect a thread from overlapping decisions in this ONE server process.
        lock = request.app.state.thread_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            snapshot = await graph.aget_state(_thread_config(thread_key(request, "draft", thread_id)))
            if not snapshot.values:
                raise HTTPException(status_code=404, detail="unknown thread_id")
            if "approval" not in snapshot.next:
                raise HTTPException(status_code=409, detail="thread is not awaiting approval")
            outcome = await graph.ainvoke(factory(body.approved), config=_thread_config(thread_key(request, "draft", thread_id)))
            return {
                "thread_id": thread_id,
                "status": outcome.get("status", "unknown"),
                "task": outcome.get("task"),
                "error": outcome.get("error"),
            }

    @app.post("/v1/agent/ask", dependencies=[Depends(_check_token)])
    async def ask_agent(body: AgentQueryRequest, request: Request) -> dict:
        agent = request.app.state.live_agent
        if agent is None:
            raise HTTPException(status_code=503, detail="live Qwen disabled by default")
        outcome = await agent.ainvoke({
            "messages": [{"role": "user", "content": body.message}],
            "reference_now": body.reference_now.isoformat(),
            "llm_calls": 0,
        })
        last = outcome["messages"][-1]
        return {"answer": str(last.content), "model_calls": outcome.get("llm_calls", 0),
                "mock_tools_only": True}

    @app.post("/v1/agent/stream", dependencies=[Depends(_check_token)])
    async def stream_agent(body: AgentQueryRequest, request: Request):
        agent = request.app.state.live_agent
        if agent is None:
            raise HTTPException(status_code=503, detail="live Qwen disabled by default")

        async def events() -> AsyncIterator[str]:
            last_content = ""
            try:
                async for update in agent.astream({
                    "messages": [{"role": "user", "content": body.message}],
                    "reference_now": body.reference_now.isoformat(), "llm_calls": 0,
                }, stream_mode="updates"):
                    for node, patch in update.items():
                        yield _encode_sse("progress", {"node": node, "status": "completed"})
                        if node == "agent" and isinstance(patch, dict):
                            for msg in patch.get("messages", []):
                                if isinstance(getattr(msg, "content", None), str) and msg.content:
                                    last_content = msg.content
                yield _encode_sse("done", {"answer": last_content, "mock_tools_only": True})
            except Exception:  # noqa: BLE001 -- SSE boundary returns a sanitized terminal error.
                yield _encode_sse("error", {"message": "agent execution failed"})

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app

"""Existing system, calendar, draft approval and mock-tool HTTP routes."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from importlib.resources import files
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from productivity_agent.interfaces.http.dependencies import (
    _check_token,
    authorize_thread,
    claim_thread,
    identity_for,
    resources_for,
    thread_key,
)
from productivity_agent.interfaces.http.schemas import (
    AgentQueryRequest,
    CalendarCheckRequest,
    DecisionRequest,
    NaturalLanguageCalendarRequest,
    TaskDraftRequest,
)
from productivity_agent.interfaces.http.streaming import _encode_sse


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


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


def api_router():
    app = APIRouter()

    @app.get("/", include_in_schema=False)
    async def home():
        return RedirectResponse(url="/app", status_code=307)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "personal-productivity-agent", "version": "1.0.0"}

    @app.get("/app", include_in_schema=False)
    async def dashboard():
        path = files("productivity_agent").joinpath("static", "index.html")
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

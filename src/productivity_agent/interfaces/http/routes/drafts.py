"""Drafts HTTP routes; resources remain request-bound."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from productivity_agent.interfaces.http.dependencies import (
    _check_token,
    authorize_thread,
    claim_thread,
    identity_for,
    resources_for,
    thread_key,
)
from productivity_agent.interfaces.http.schemas import DecisionRequest, TaskDraftRequest

router = APIRouter()


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


@router.post("/v1/tasks/drafts", status_code=201, dependencies=[Depends(_check_token)])
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


@router.get("/v1/tasks/drafts/{thread_id}", dependencies=[Depends(_check_token)])
async def get_task_draft(thread_id: str, request: Request) -> dict:
    authorize_thread(request, "draft", thread_id)
    snapshot = await resources_for(request).approval_graph.aget_state(_thread_config(thread_key(request, "draft", thread_id)))
    return _snapshot_response(thread_id, snapshot)


@router.post("/v1/tasks/drafts/{thread_id}/decision", dependencies=[Depends(_check_token)])
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

"""Unified session transport; all writes remain inside the persisted approval graph."""
import asyncio
import json
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator

from productivity_agent.api.resources import resources_for
from productivity_agent.services.identity import (
    authorize_thread,
    claim_thread,
    identity_for,
    thread_key,
)


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    reference_now: AwareDatetime
    timezone: str = "Asia/Shanghai"
    message_id: uuid.UUID

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: StrictBool
    operation_id: uuid.UUID


def config(thread_id):
    return {"configurable": {"thread_id": f"assistant:{thread_id}"}, "recursion_limit": 20}


def view(thread_id, snapshot):
    state = snapshot.values
    waiting = "approval" in snapshot.next
    status = "awaiting_approval" if waiting else "interrupted" if snapshot.next else state["status"]
    return {
        "thread_id": str(thread_id), "status": status, "reply": state.get("reply", ""),
        "result": state.get("result"), "history": state.get("history", []),
        "approval": {"operation_id": state["operation_id"], "title": state["title"],
                     "due_at": state["due_at"], "action": (state.get("intent") or {}).get("action", "create_task"),
                     "before": state.get("target"), "changes": state.get("patch")} if waiting else None,
    }


def assistant_router(check_token):
    router = APIRouter(prefix="/v1/assistant", dependencies=[Depends(check_token)])

    def graph_for(request):
        graph = resources_for(request).assistant_graph
        if graph is None:
            raise HTTPException(503, "Unified assistant unavailable")
        return graph

    def owned_config(request, tid):
        return {"configurable": {"thread_id": thread_key(request, "assistant", tid)}, "recursion_limit": 20}

    async def snapshot_for(request, tid):
        authorize_thread(request, "assistant", tid)
        snapshot = await graph_for(request).aget_state(owned_config(request, tid))
        if not snapshot.values:
            raise HTTPException(404, "Unknown assistant session")
        return snapshot

    def lock_for(request, tid):
        return request.app.state.thread_locks.setdefault(f"assistant:{tid}", asyncio.Lock())

    @router.post("/sessions", status_code=201)
    async def create(request: Request):
        tid = uuid.uuid4()
        claim_thread(request, "assistant", tid)
        await graph_for(request).ainvoke({"initialize": True, "owner_id": identity_for(request).owner_id}, owned_config(request, tid))
        return view(tid, await snapshot_for(request, tid))

    @router.get("/sessions/{thread_id}")
    async def get(thread_id: uuid.UUID, request: Request):
        return view(thread_id, await snapshot_for(request, thread_id))

    async def turn(request, tid, body):
        graph = graph_for(request)
        async with lock_for(request, tid):
            snapshot = await snapshot_for(request, tid)
            if snapshot.values.get("last_message_id") == str(body.message_id):
                if snapshot.values.get("user_text") != body.message:
                    raise HTTPException(409, "message_id already used for another message")
                yield "done", view(tid, snapshot)
                return
            if snapshot.next:
                raise HTTPException(409, "请先批准/拒绝待确认操作，或恢复中断执行。")
            payload = {"request_id": str(uuid.uuid4()), "thread_id": str(tid), "initialize": False, "user_text": body.message,
                       "reference_now": body.reference_now.isoformat(), "timezone": body.timezone,
                       "last_message_id": str(body.message_id)}
            async for update in graph.astream(payload, owned_config(request, tid), stream_mode="updates"):
                for node in update:
                    if node != "__interrupt__":
                        yield "progress", {"node": node}
            yield "done", view(tid, await snapshot_for(request, tid))

    @router.post("/sessions/{thread_id}/messages")
    async def message(thread_id: uuid.UUID, body: MessageRequest, request: Request):
        result = None
        async for event, data in turn(request, thread_id, body):
            if event == "done":
                result = data
        return result

    @router.post("/sessions/{thread_id}/messages/stream")
    async def stream(thread_id: uuid.UUID, body: MessageRequest, request: Request):
        await snapshot_for(request, thread_id)

        async def events():
            try:
                async for event, data in turn(request, thread_id, body):
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            except HTTPException as exc:
                yield f"event: error\ndata: {json.dumps({'message': exc.detail})}\n\n"
            except Exception:  # noqa: BLE001 -- stream headers sent; never expose checkpoints/errors.
                yield 'event: error\ndata: {"message":"执行中断，请查询会话状态后恢复。"}\n\n'

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @router.post("/sessions/{thread_id}/decision")
    async def decide(thread_id: uuid.UUID, body: ApprovalRequest, request: Request):
        from langgraph.types import Command
        async with lock_for(request, thread_id):
            snapshot = await snapshot_for(request, thread_id)
            if snapshot.values.get("operation_id") != str(body.operation_id):
                raise HTTPException(409, "操作已改变，请重新查询待确认内容。")
            if "approval" not in snapshot.next:
                if not snapshot.next and snapshot.values.get("approved") is body.approved:
                    return view(thread_id, snapshot)
                raise HTTPException(409, "当前操作不在待审批状态。")
            await graph_for(request).ainvoke(Command(resume=body.approved), owned_config(request, thread_id))
            return view(thread_id, await snapshot_for(request, thread_id))

    @router.post("/sessions/{thread_id}/recover")
    async def recover(thread_id: uuid.UUID, request: Request):
        async with lock_for(request, thread_id):
            snapshot = await snapshot_for(request, thread_id)
            if snapshot.next and "approval" not in snapshot.next:
                await graph_for(request).ainvoke(None, owned_config(request, thread_id))
            return view(thread_id, await snapshot_for(request, thread_id))

    return router

"""Agent HTTP routes; resources remain request-bound."""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from productivity_agent.interfaces.http.dependencies import _check_token
from productivity_agent.interfaces.http.schemas import AgentQueryRequest
from productivity_agent.interfaces.http.streaming import _encode_sse

router = APIRouter()


@router.post("/v1/agent/ask", dependencies=[Depends(_check_token)])
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


@router.post("/v1/agent/stream", dependencies=[Depends(_check_token)])
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

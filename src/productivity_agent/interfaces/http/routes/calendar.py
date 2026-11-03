"""Calendar HTTP routes; resources remain request-bound."""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from productivity_agent.interfaces.http.dependencies import _check_token
from productivity_agent.interfaces.http.schemas import (
    CalendarCheckRequest,
    NaturalLanguageCalendarRequest,
)
from productivity_agent.interfaces.http.streaming import _encode_sse

router = APIRouter()


@router.post("/v1/calendar/natural-language", dependencies=[Depends(_check_token)])
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


@router.post("/v1/calendar/check", dependencies=[Depends(_check_token)])
async def calendar_check(body: CalendarCheckRequest, request: Request) -> dict:
    outcome = await request.app.state.calendar_graph.ainvoke(body.to_graph_input())
    return {"result": outcome["result"]}


@router.post("/v1/calendar/check/stream", dependencies=[Depends(_check_token)])
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

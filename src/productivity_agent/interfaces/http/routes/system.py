"""System HTTP routes; resources remain request-bound."""
from __future__ import annotations

from importlib.resources import files

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse

from productivity_agent.interfaces.http.dependencies import _check_token, identity_for

router = APIRouter()


@router.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/app", status_code=307)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "personal-productivity-agent", "version": "1.0.0"}


@router.get("/app", include_in_schema=False)
async def dashboard():
    path = files("productivity_agent").joinpath("static", "index.html")
    return FileResponse(path, media_type="text/html")


@router.get("/v1/system", dependencies=[Depends(_check_token)])
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


@router.get("/v1/me", dependencies=[Depends(_check_token)])
async def me(request: Request):
    return {"owner_id": identity_for(request).owner_id, "auth_enabled": request.app.state.accounts.enabled}

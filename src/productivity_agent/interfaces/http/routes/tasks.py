"""Tasks HTTP routes; resources remain request-bound."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from productivity_agent.interfaces.http.dependencies import _check_token, resources_for

router = APIRouter()


@router.get("/v1/tasks", dependencies=[Depends(_check_token)])
async def list_tasks(request: Request, limit: int = 100) -> dict:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be 1..100")
    # SQLiteTaskStore is synchronous; avoid blocking the event loop.
    records = await asyncio.to_thread(resources_for(request).store.list_tasks, limit=limit)
    return {"items": records, "count": len(records)}


@router.get("/v1/tasks/{task_id}", dependencies=[Depends(_check_token)])
async def task_detail(task_id: str, request: Request):
    try:
        return await asyncio.to_thread(resources_for(request).store.get_task, task_id)
    except KeyError:
        raise HTTPException(404, "resource_not_found") from None


@router.get("/v1/operations/{operation_id}", dependencies=[Depends(_check_token)])
async def operation_detail(operation_id: str, request: Request):
    result = await asyncio.to_thread(resources_for(request).store.get_operation, operation_id)
    if result is None:
        raise HTTPException(404, "resource_not_found")
    return {"operation": result}

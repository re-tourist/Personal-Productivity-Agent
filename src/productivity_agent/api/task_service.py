"""Local test business service; loopback only, not an enterprise production API."""
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool

from productivity_agent.services.task_store import (
    IdempotencyConflict,
    SQLiteTaskStore,
    VersionConflict,
)


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    approved: StrictBool


class CreateRequest(WriteRequest):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime


class ChangeRequest(WriteRequest):
    expected_version: int = Field(ge=1, strict=True)
    action: str
    title: str | None = None
    due_at: AwareDatetime | None = None


def create_task_service(store=None):
    from productivity_agent.services.operation_trace import configure_logging
    configure_logging()
    store = store or SQLiteTaskStore(Path(os.getenv("PPA_DATA_DIR", ".ppa-data")) / "tasks.sqlite")
    app = FastAPI(title="PPA local test business service")

    @app.middleware("http")
    async def trace(request: Request, call_next):
        start = time.monotonic()
        try:
            rid = str(uuid.UUID(request.headers.get("X-Request-ID", "")))
        except ValueError:
            rid = str(uuid.uuid4())
        response = await call_next(request)
        logging.getLogger("ppa.business").info(
            '{"request_id":"%s","method":"%s","http_status":%d,"elapsed_ms":%.2f}',
            rid, request.method, response.status_code, (time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(status_code=400, content={"detail": "invalid_request"})

    def run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyError:
            raise HTTPException(404, "task_not_found") from None
        except (VersionConflict, IdempotencyConflict):
            raise HTTPException(409, "conflict_read_again") from None
        except ValueError:
            raise HTTPException(400, "invalid_request") from None

    def require_approval(body):
        if body.approved is not True:
            raise HTTPException(400, "explicit_approval_required")

    @app.get("/health")
    def health():
        return {"status": "ok", "local_test_service": True}

    @app.get("/tasks")
    def listing(limit: int = 100):
        return {"items": run(store.list_tasks, limit=limit)}

    @app.get("/tasks/{task_id}")
    def get(task_id: str):
        return run(store.get_task, task_id)

    @app.get("/operations/{operation_id}")
    def operation(operation_id: str):
        return {"operation": store.get_operation(operation_id)}

    @app.post("/tasks")
    def create(body: CreateRequest):
        require_approval(body)
        return run(store.create_task, body.operation_id, body.title, body.due_at.isoformat())

    @app.patch("/tasks/{task_id}")
    def change(task_id: str, body: ChangeRequest):
        require_approval(body)
        return run(store.change_task, body.operation_id, task_id, body.expected_version,
                   body.action, title=body.title,
                   due_at=body.due_at.isoformat() if body.due_at else None)

    return app

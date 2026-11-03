"""Independent loopback test server with one-shot transport faults; never shipped routes."""
import asyncio
import sys
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

from productivity_agent.api.task_service import create_task_service
from productivity_agent.services.task_store import SQLiteTaskStore

root = Path(sys.argv[1])
app = create_task_service(SQLiteTaskStore(root / "tasks.sqlite"))


@app.middleware("http")
async def fault(request: Request, call_next):
    marker = root / "fault"
    mode = marker.read_text() if marker.exists() else ""
    if mode and request.method in {"POST", "PATCH"}:
        marker.unlink()
        if mode == "500":
            return JSONResponse(status_code=503, content={"detail": "injected_unavailable"})
        if mode == "before_timeout":
            await asyncio.sleep(0.5)
            return JSONResponse(status_code=503, content={"detail": "not_committed"})
        response = await call_next(request)
        if mode == "after_timeout":
            await asyncio.sleep(0.5)
        return response
    return await call_next(request)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="info")

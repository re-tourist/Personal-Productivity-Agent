"""Independent loopback test server with one-shot transport faults; never shipped routes."""
import asyncio
import sys
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

from productivity_agent.api.task_service import create_task_service
from productivity_agent.services.identity import Accounts
from productivity_agent.services.task_store import SQLiteTaskStore

root = Path(sys.argv[1])
app = create_task_service(SQLiteTaskStore(root / "tasks.sqlite"))


@app.middleware("http")
async def fault(request: Request, call_next):
    marker = root / "fault"
    mode = marker.read_text() if marker.exists() else ""
    if request.method in {"POST", "PATCH"}:
        with (root / "write-requests.txt").open("a", encoding="utf-8") as journal:
            journal.write(request.method + " " + request.url.path + "\n")
    # B0 characterization adds faults only to this synthetic test server.
    # Failed reconciliation must stay distinguishable from an absent operation.
    if mode in {"read_5xx", "read_timeout"} and request.url.path.startswith("/operations/"):
        marker.unlink()
        if mode == "read_timeout":
            await asyncio.sleep(0.5)
        return JSONResponse(status_code=503, content={"detail": "injected_read_unavailable"})
    if mode and request.method in {"POST", "PATCH"}:
        marker.unlink()
        if mode == "500":
            return JSONResponse(status_code=503, content={"detail": "injected_unavailable"})
        if mode == "before_timeout":
            await asyncio.sleep(0.5)
            return JSONResponse(status_code=503, content={"detail": "not_committed"})
        if mode == "identity_downgrade":
            app.state.accounts = Accounts()
        response = await call_next(request)
        if mode in {"after_timeout_read_5xx", "after_5xx_read_5xx"}:
            marker.write_text("read_5xx")
        if mode in {"after_timeout", "after_timeout_read_5xx"}:
            await asyncio.sleep(0.5)
        if mode in {"after_5xx", "after_5xx_read_5xx"}:
            return JSONResponse(status_code=503, content={"detail": "injected_after_commit_unavailable"})
        return response
    return await call_next(request)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="info")

"""HTTP authentication and request tracing; persistence lives in Infrastructure."""
import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from productivity_agent.bootstrap import configured_accounts


def install_identity(app, *, business=False):
    app.state.accounts = configured_accounts()

    @app.middleware("http")
    async def verify(request: Request, call_next):
        protected = request.url.path.startswith(("/tasks", "/operations", "/identity")) if business else request.url.path.startswith("/v1/")
        if protected:
            authorization = request.headers.get("Authorization", "")
            # A business-service downgrade must not reinterpret an authenticated
            # caller as the legacy owner, including between identity/read-write calls.
            identity = (None if business and not app.state.accounts.enabled and authorization
                        else app.state.accounts.authenticate(authorization))
            if identity is None:
                return JSONResponse(status_code=401, content={"detail": "authentication_required"},
                                    headers={"WWW-Authenticate": "Bearer"})
            request.state.identity = identity
        return await call_next(request)


def install_business_trace(app):
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

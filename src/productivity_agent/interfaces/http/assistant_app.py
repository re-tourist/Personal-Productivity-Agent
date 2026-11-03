"""Assistant HTTP app factory. Resource lifetime is owned by bootstrap."""
from typing import Any

from fastapi import FastAPI

from productivity_agent.bootstrap import assistant_lifespan
from productivity_agent.interfaces.http.dependencies import _check_token
from productivity_agent.interfaces.http.middleware import install_identity
from productivity_agent.interfaces.http.routes.api import api_router
from productivity_agent.interfaces.http.routes.assistant import assistant_router


def create_app(
    *,
    approval_graph: Any = None,
    calendar_graph: Any = None,
    store: Any = None,
    live_agent: Any = None,
    intent_graph: Any = None,
    api_token: str | None = None,
    command_factory: Any = None,
    session_extractor: Any = None,
    session_backend: Any = None,
) -> FastAPI:
    """Create an app. Inject fake graphs/stores for offline HTTP tests.

    In normal mode resources are opened during lifespan, not import time.
    A single process is required: per-thread locks are in-process only.
    """
    app = FastAPI(
        title="Personal Productivity Agent", version="1.0.0",
        lifespan=assistant_lifespan(
            approval_graph=approval_graph, calendar_graph=calendar_graph, store=store,
            live_agent=live_agent, intent_graph=intent_graph, api_token=api_token,
            command_factory=command_factory, session_extractor=session_extractor,
            session_backend=session_backend,
        ),
    )
    install_identity(app)
    app.include_router(assistant_router(_check_token))
    app.include_router(api_router())
    return app

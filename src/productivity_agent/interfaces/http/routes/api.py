"""Compose the existing route groups in their original matching order.

Private draft helpers are re-exported for R1 compatibility; new code uses drafts.
"""
from fastapi import APIRouter

from productivity_agent.interfaces.http.routes.agent import router as agent_router
from productivity_agent.interfaces.http.routes.calendar import router as calendar_router
from productivity_agent.interfaces.http.routes.drafts import (
    _snapshot_response,
    _thread_config,
)
from productivity_agent.interfaces.http.routes.drafts import (
    router as drafts_router,
)
from productivity_agent.interfaces.http.routes.system import router as system_router
from productivity_agent.interfaces.http.routes.tasks import router as tasks_router

__all__ = ["_snapshot_response", "_thread_config", "api_router"]


def api_router():
    router = APIRouter()
    router.include_router(system_router)
    router.include_router(tasks_router)
    router.include_router(calendar_router)
    router.include_router(drafts_router)
    router.include_router(agent_router)
    return router

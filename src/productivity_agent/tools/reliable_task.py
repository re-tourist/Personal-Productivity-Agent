"""Legacy import facade; internal callers use Application (R2 compatibility)."""
from productivity_agent.application.agent.tools.reliable_task import (
    build_safe_create_task_tool,
)

__all__ = ['build_safe_create_task_tool']

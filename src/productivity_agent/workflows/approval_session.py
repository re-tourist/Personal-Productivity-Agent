"""Legacy import facade; internal callers use Application (R2 compatibility)."""
from productivity_agent.application.agent.workflows.approval_session import (
    ApprovalState,
    build_approval_graph,
    request_task_approval,
)

__all__ = ['ApprovalState', 'build_approval_graph', 'request_task_approval']

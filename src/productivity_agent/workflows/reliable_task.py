"""Legacy M4 facade; single implementation in Application (R2 compatibility)."""
from productivity_agent.application.agent.workflows.reliable_task import (
    ReliableTaskState,
    build_reliable_task_graph,
)

__all__ = ["ReliableTaskState", "build_reliable_task_graph"]

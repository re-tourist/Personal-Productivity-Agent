"""Optional M4 write tool. Keep operation identity outside the model's control."""

from langchain_core.tools import tool

from productivity_agent.services.task_store import SQLiteTaskStore
from productivity_agent.workflows.reliable_task import build_reliable_task_graph


def build_safe_create_task_tool(store: SQLiteTaskStore, operation_id: str):
    """One tool for ONE authorized logical operation.

    The trusted caller creates and persists operation_id before exposing this tool.
    Use a different operation_id for each separately approved task.
    """
    graph = build_reliable_task_graph(store)

    @tool
    def create_task(title: str, due_at: str) -> dict:
        """Create one task in the LOCAL MOCK DB. due_at must include timezone; never affects real accounts."""
        result = graph.invoke({
            "operation_id": operation_id,
            "title": title,
            "due_at": due_at,
            "max_attempts": 3,
        })
        return {
            "status": result["status"],
            "operation_id": operation_id,
            "task": result.get("task"),
            "error": result.get("error"),
            "mock_only": True,
        }

    return create_task

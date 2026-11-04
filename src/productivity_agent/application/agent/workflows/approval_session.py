"""M5: resumable approval workflow, backed by LangGraph checkpoints.

The checkpointer owns execution snapshots. M4 SQLiteTaskStore owns durable task
records and idempotency. Never perform external writes before interrupt().
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from productivity_agent.application.agent.workflows.reliable_task import build_reliable_task_graph
from productivity_agent.application.ports.tasks import TaskCreator
from productivity_agent.domain.tasks import validate_task_request


class ApprovalState(TypedDict):
    owner_id: NotRequired[str]
    operation_id: str
    title: str
    due_at: str
    status: NotRequired[str]
    approved: NotRequired[bool]
    task: NotRequired[dict | None]
    error: NotRequired[str | None]


def request_task_approval(state: ApprovalState) -> dict:
    """Shared M5 boundary: a resumed node must not write before explicit approval."""
    decision = interrupt({
        "type": "task_creation_approval", "operation_id": state["operation_id"],
        "title": state["title"], "due_at": state["due_at"],
        "question": "是否确认本次任务操作？",
        "before": state.get("target"), "changes": state.get("patch"),
        "action": (state.get("intent") or {}).get("action", "create_task"),
    })
    if type(decision) is not bool:
        raise ValueError("resume payload must be a boolean: true or false")
    return {"approved": decision, "status": "approved" if decision else "cancelled"}


def build_approval_graph(store: TaskCreator, checkpointer):
    """One logical write per thread; resume with Command(resume=...).

    The caller must authorize thread access and persist the operation_id.
    Never resume a completed thread as if it were a new independent write.
    """

    def validate(state: ApprovalState) -> dict:
        try:
            validate_task_request(state["operation_id"], state["title"], state["due_at"])
        except (ValueError, KeyError, TypeError) as exc:
            return {"status": "invalid", "error": str(exc)}
        return {"status": "awaiting_approval", "error": None}

    def after_validation(state: ApprovalState) -> str:
        return "approval" if state["status"] == "awaiting_approval" else END

    def approval(state: ApprovalState) -> dict:
        # Only pure/read-only operations are allowed before interrupt():
        # this node is re-executed from its start on resume.
        return request_task_approval(state)

    def after_approval(state: ApprovalState) -> str:
        return "execute" if state["approved"] is True else END

    def execute(state: ApprovalState) -> dict:
        # M4 has transactional idempotency: checkpoint + write are NOT atomic.
        result = build_reliable_task_graph(store).invoke({
            "operation_id": state["operation_id"],
            "title": state["title"],
            "due_at": state["due_at"],
            "max_attempts": 3,
        })
        return {
            "status": result["status"],
            "task": result.get("task"),
            "error": result.get("error"),
        }

    builder = StateGraph(ApprovalState)
    builder.add_node("validate", validate)
    builder.add_node("approval", approval)
    builder.add_node("execute", execute)
    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", after_validation)
    builder.add_conditional_edges("approval", after_approval)
    builder.add_edge("execute", END)
    return builder.compile(checkpointer=checkpointer)

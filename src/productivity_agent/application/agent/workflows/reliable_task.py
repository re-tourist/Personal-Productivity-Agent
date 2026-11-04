"""Checkpoint-compatible M4 driver over the shared creation policy.

The nested driver is intentional: historical parent execute nodes persist its
namespace. Keep node names, State, routing and invocation order unchanged.
"""
from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from productivity_agent.application.ports.tasks import TaskCreator
from productivity_agent.application.use_cases.task_creation import (
    attempt_creation,
    reconcile_creation,
    retry_creation,
    validate_creation,
)


class ReliableTaskState(TypedDict):
    operation_id: str
    title: str
    due_at: str
    attempts: NotRequired[int]
    max_attempts: NotRequired[int]
    status: NotRequired[str]
    last_error_type: NotRequired[str | None]
    error: NotRequired[str | None]
    task: NotRequired[dict | None]


def build_reliable_task_graph(
    store: TaskCreator,
    *,
    fault_plan: dict[int, str] | None = None,
):
    """One logical creation; fault_plan retains the old test/demo-only seam.

    Adapter fault kwargs are not part of the production TaskCreator contract.
    Parent config/checkpointer is inherited by LangGraph as before.
    """
    faults = fault_plan or {}

    def validate(state: ReliableTaskState) -> dict:
        return validate_creation(state)

    def after_validation(state: ReliableTaskState) -> Literal["attempt_create", "__end__"]:
        return "attempt_create" if state["status"] == "ready" else END

    def attempt_create(state: ReliableTaskState) -> dict:
        if fault_plan is not None:
            # Existing SQLite/HTTP demo implementations accept this extra seam.
            # Ordinary structural Port implementations need not accept fault.
            def create(operation_id, title, due_at):
                return store.create_task(operation_id, title, due_at,
                                         fault=faults.get(state.get("attempts", 0) + 1))
        else:
            create = store.create_task
        return attempt_creation(state, create)

    def after_attempt(state: ReliableTaskState) -> Literal["reconcile", "retry_gate", "__end__"]:
        if state["status"] == "ambiguous":
            return "reconcile"
        if state["status"] == "retryable":
            return "retry_gate"
        return END

    def reconcile(state: ReliableTaskState) -> dict:
        return reconcile_creation(store, state)

    def after_reconcile(state: ReliableTaskState) -> Literal["retry_gate", "__end__"]:
        return "retry_gate" if state["status"] == "retryable" else END

    def retry_gate(state: ReliableTaskState) -> dict:
        return retry_creation(state)

    def after_retry_gate(state: ReliableTaskState) -> Literal["attempt_create", "__end__"]:
        return "attempt_create" if state["status"] == "retrying" else END

    builder = StateGraph(ReliableTaskState)
    builder.add_node("validate", validate)
    builder.add_node("attempt_create", attempt_create)
    builder.add_node("reconcile", reconcile)
    builder.add_node("retry_gate", retry_gate)
    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", after_validation)
    builder.add_conditional_edges("attempt_create", after_attempt)
    builder.add_conditional_edges("reconcile", after_reconcile)
    builder.add_conditional_edges("retry_gate", after_retry_gate)
    return builder.compile()

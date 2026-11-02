"""M4: failure classification, bounded retries, and reconciliation graph.

Write outcomes are backed by a durable SQLite operation index. No LLM is needed:
recovering a known side-effect is a deterministic infrastructure concern.
"""

from __future__ import annotations

import sqlite3
from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from productivity_agent.services.task_store import (
    AmbiguousCommitError,
    IdempotencyConflict,
    SQLiteTaskStore,
    TransientWriteError,
    validate_task_request,
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
    store: SQLiteTaskStore,
    *,
    fault_plan: dict[int, str] | None = None,
):
    """Build a graph for a *single* logical task creation operation.

    fault_plan is ONLY for deterministic tests/demos; e.g. {1: 'after_commit'}.
    M5 will introduce graph checkpoints, separate from business transaction storage.
    """
    faults = fault_plan or {}

    def validate(state: ReliableTaskState) -> dict:
        try:
            validate_task_request(state["operation_id"], state["title"], state["due_at"])
            limit = state.get("max_attempts", 3)
            if not isinstance(limit, int) or not 1 <= limit <= 5:
                raise ValueError("max_attempts must be in 1..5")
        except (ValueError, TypeError, KeyError) as exc:
            return {"status": "failed", "error": str(exc), "last_error_type": "permanent"}
        return {"status": "ready", "attempts": 0, "error": None}

    def after_validation(state: ReliableTaskState) -> Literal["attempt_create", "__end__"]:
        return "attempt_create" if state["status"] == "ready" else END

    def attempt_create(state: ReliableTaskState) -> dict:
        attempt = state.get("attempts", 0) + 1
        args = (state["operation_id"], state["title"], state["due_at"])
        try:
            result = store.create_task(*args, fault=faults.get(attempt))
        except AmbiguousCommitError as exc:
            return {
                "attempts": attempt, "status": "ambiguous",
                "last_error_type": "ambiguous", "error": str(exc),
            }
        except (TransientWriteError, ConnectionError, sqlite3.OperationalError) as exc:
            return {
                "attempts": attempt, "status": "retryable",
                "last_error_type": "transient", "error": str(exc),
            }
        except (IdempotencyConflict, ValueError) as exc:
            return {
                "attempts": attempt, "status": "failed",
                "last_error_type": "permanent", "error": str(exc),
            }
        return {
            "attempts": attempt,
            "status": "recovered" if result["status"] == "replayed" else "created",
            "task": result["task"], "error": None,
            "last_error_type": None,
        }

    def after_attempt(state: ReliableTaskState) -> Literal["reconcile", "retry_gate", "__end__"]:
        if state["status"] == "ambiguous":
            return "reconcile"
        if state["status"] == "retryable":
            return "retry_gate"
        return END

    def reconcile(state: ReliableTaskState) -> dict:
        try:
            task = store.lookup(state["operation_id"], state["title"], state["due_at"])
        except IdempotencyConflict as exc:
            return {"status": "failed", "last_error_type": "permanent", "error": str(exc)}
        except (ConnectionError, sqlite3.OperationalError) as exc:
            return {
                "status": "retryable", "last_error_type": "ambiguous",
                "error": f"reconciliation unavailable: {exc}",
            }
        if task is not None:
            return {"status": "recovered", "task": task, "error": None}
        # With this SQLite local service, a missing row means no committed task.
        # Do not generalize this conclusion to eventually consistent external APIs.
        return {"status": "retryable", "last_error_type": "ambiguous"}

    def after_reconcile(state: ReliableTaskState) -> Literal["retry_gate", "__end__"]:
        return "retry_gate" if state["status"] == "retryable" else END

    def retry_gate(state: ReliableTaskState) -> dict:
        if state["attempts"] < state.get("max_attempts", 3):
            return {"status": "retrying"}
        return {
            "status": "needs_review" if state.get("last_error_type") == "ambiguous" else "failed",
            "error": state.get("error") or "retry budget exhausted",
        }

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

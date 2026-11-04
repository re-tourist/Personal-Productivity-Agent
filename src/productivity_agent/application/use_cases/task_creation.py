"""Reliable creation steps shared by ordinary callers and checkpointed drivers.

No Agent, Tool or Graph dependency. SQLite OperationalError is deliberately
retained as a legacy failure contract, not converted into a known non-commit.
No SQL/transactions live here. HTTP reconciliation errors keep propagating.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping

from productivity_agent.application.ports.tasks import (
    AmbiguousCommitError,
    TaskCreator,
    TransientWriteError,
)
from productivity_agent.domain.tasks import IdempotencyConflict, validate_task_request


def create_task_once(store: TaskCreator, operation_id: str, title: str, due_at: str) -> dict:
    """One authorized write, preserving the Adapter's receipt and exceptions.

    Used by the Business HTTP boundary after its existing explicit approval check.
    Never introduces retries at the service boundary.
    """
    return store.create_task(operation_id, title, due_at)


def validate_creation(state: Mapping) -> dict:
    try:
        validate_task_request(state["operation_id"], state["title"], state["due_at"])
        limit = state.get("max_attempts", 3)
        if not isinstance(limit, int) or not 1 <= limit <= 5:
            raise ValueError("max_attempts must be in 1..5")
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "failed", "error": str(exc), "last_error_type": "permanent"}
    return {"status": "ready", "attempts": 0, "error": None}


def attempt_creation(state: Mapping, create: Callable[[str, str, str], dict]) -> dict:
    attempt = state.get("attempts", 0) + 1
    args = (state["operation_id"], state["title"], state["due_at"])
    try:
        result = create(*args)
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


def reconcile_creation(store: TaskCreator, state: Mapping) -> dict:
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
    # Only the current local/loopback transactional contract supports this retry.
    # Do not generalize a missing operation to eventually consistent services.
    return {"status": "retryable", "last_error_type": "ambiguous"}


def retry_creation(state: Mapping) -> dict:
    if state["attempts"] < state.get("max_attempts", 3):
        return {"status": "retrying"}
    return {
        "status": "needs_review" if state.get("last_error_type") == "ambiguous" else "failed",
        "error": state.get("error") or "retry budget exhausted",
    }


def create_task_reliably(
    store: TaskCreator, operation_id: str, title: str, due_at: str, *,
    approved: bool, max_attempts: int = 3,
) -> dict:
    """Run the shared policy without a framework, after a trusted approval.

    Checkpointed callers retain their node driver instead of entering this loop:
    checkpoint/write atomicity is not assumed. Errors outside the old catch sets
    propagate, including HTTP reconciliation unavailability.
    """
    if type(approved) is not bool:
        raise ValueError("approved must be a boolean")
    state = {"operation_id": operation_id, "title": title, "due_at": due_at,
             "max_attempts": max_attempts}
    if not approved:
        return {**state, "status": "cancelled", "task": None, "error": None}
    state.update(validate_creation(state))
    if state["status"] != "ready":
        return state
    while True:
        state.update(attempt_creation(state, store.create_task))
        if state["status"] == "ambiguous":
            state.update(reconcile_creation(store, state))
        if state["status"] == "retryable":
            state.update(retry_creation(state))
        if state["status"] != "retrying":
            return state


def verify_created_task(
    store: TaskCreator, operation_id: str, title: str, due_at: str, outcome: Mapping,
) -> dict | None:
    """Check a claimed result against the same request and durable Task ID.

    None means the result could not be verified, never that a write did not occur.
    Read failures propagate to each caller's existing error boundary.
    """
    task = store.lookup(operation_id, title, due_at)
    if task is None or task["id"] != outcome["task"]["id"]:
        return None
    return task

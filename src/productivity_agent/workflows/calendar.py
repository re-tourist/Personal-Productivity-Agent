"""M1: deterministic calendar-conflict workflow.

Graph: START -> validate_request -> (reject | check_conflict)
       check_conflict -> (mark_available | suggest_alternative) -> END
No real calendar writes occur in this workflow.
"""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from productivity_agent.domain.calendar_rules import (
    overlaps, has_conflict, next_available_slot
)
from productivity_agent.domain.state import CalendarState
from productivity_agent.domain.time_utils import as_interval


def validate_request(state: CalendarState) -> dict:
    """Validate the calendar request and mock busy slots."""
    try:
        request = state["request"]
        if not request["title"].strip():
            raise ValueError("Schedule title must be non-empty")
        as_interval(request)
        for slot in state["busy_slots"]:
            as_interval(slot)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"error": str(exc)}
    return {"error": None}


def reject(state: CalendarState) -> dict:
    return {
        "result": {
            "status": "invalid",
            "message": state.get("error") or "Invalid request",
        }
    }


def check_conflict(state: CalendarState) -> dict:
    """Read input state and produce a partial state update."""
    return {"conflict": has_conflict(state["request"], state["busy_slots"])}


def route_after_validation(state: CalendarState) -> Literal["reject", "check_conflict"]:
    return "reject" if state.get("error") else "check_conflict"


def route_after_check(
    state: CalendarState,
) -> Literal["mark_available", "suggest_alternative"]:
    return "suggest_alternative" if state["conflict"] else "mark_available"


def mark_available(state: CalendarState) -> dict:
    return {
        "result": {
            "status": "available",
            "message": "No calendar conflict. Nothing has been created.",
        }
    }


def suggest_alternative(state: CalendarState) -> dict:
    """Keep recommendation logic in the pure domain layer."""
    candidate = next_available_slot(state["request"], state["busy_slots"])
    if candidate:
        return {"result": {
            "status": "conflict",
            "message": "Requested time is busy. An alternative is available; no event created.",
            "suggested_start": candidate["start_at"],
            "suggested_end": candidate["end_at"],
        }}
    return {"result": {
        "status": "no_available_slot",
        "message": "No same-day alternative ends by the scheduling cutoff.",
    }}


def build_graph():
    builder = StateGraph(CalendarState)
    builder.add_node("validate_request", validate_request)
    builder.add_node("reject", reject)
    builder.add_node("check_conflict", check_conflict)
    builder.add_node("mark_available", mark_available)
    builder.add_node("suggest_alternative", suggest_alternative)

    builder.add_edge(START, "validate_request")
    builder.add_conditional_edges("validate_request", route_after_validation)
    builder.add_conditional_edges("check_conflict", route_after_check)
    builder.add_edge("reject", END)
    builder.add_edge("mark_available", END)
    builder.add_edge("suggest_alternative", END)

    return builder.compile()

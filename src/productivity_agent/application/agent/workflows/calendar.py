"""M1: deterministic calendar-conflict workflow.

Graph: START -> validate_request -> (reject | check_conflict)
       check_conflict -> (mark_available | suggest_alternative) -> END
No real calendar writes occur in this workflow.
"""

from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from productivity_agent.application.use_cases.calendar import (
    alternative_result,
    available_result,
    invalid_result,
    validation_error,
)
from productivity_agent.domain.calendar_rules import has_conflict
from productivity_agent.domain.contracts import CalendarRequest, DecisionResult, TimeSlot


class CalendarState(TypedDict):
    request: CalendarRequest
    busy_slots: list[TimeSlot]
    error: NotRequired[str | None]
    conflict: NotRequired[bool]
    result: NotRequired[DecisionResult]


def validate_request(state: CalendarState) -> dict:
    """Validate the calendar request and mock busy slots."""
    return {"error": validation_error(state)}


def reject(state: CalendarState) -> dict:
    return {"result": invalid_result(state.get("error"))}


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
    return {"result": available_result()}


def suggest_alternative(state: CalendarState) -> dict:
    """Keep recommendation logic in the pure domain layer."""
    return {"result": alternative_result(state["request"], state["busy_slots"])}


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

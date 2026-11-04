"""Legacy M1 imports; main implementation lives in Application (R2-B1)."""
from productivity_agent.application.agent.workflows.calendar import (
    CalendarState,
    build_graph,
    check_conflict,
    mark_available,
    reject,
    route_after_check,
    route_after_validation,
    suggest_alternative,
    validate_request,
)
from productivity_agent.domain.calendar_rules import has_conflict, next_available_slot, overlaps
from productivity_agent.domain.time_utils import as_interval

__all__ = [
    "CalendarState",
    "as_interval",
    "build_graph",
    "check_conflict",
    "has_conflict",
    "mark_available",
    "next_available_slot",
    "overlaps",
    "reject",
    "route_after_check",
    "route_after_validation",
    "suggest_alternative",
    "validate_request",
]

"""Approved legacy Domain facade (1/3); new callers use final owners directly."""
from productivity_agent.application.agent.workflows.calendar import CalendarState
from productivity_agent.domain.contracts import CalendarRequest, DecisionResult, TimeSlot

__all__ = ["CalendarRequest", "CalendarState", "DecisionResult", "TimeSlot"]

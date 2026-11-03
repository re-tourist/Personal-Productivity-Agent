"""Historical graph state, deferred to Application in R2. Business contracts are re-exported."""
from typing import NotRequired, TypedDict

from productivity_agent.domain.contracts import CalendarRequest, DecisionResult, TimeSlot


class CalendarState(TypedDict):
    request: CalendarRequest
    busy_slots: list[TimeSlot]  # M1 mock data; will be fetched by tools in M3
    error: NotRequired[str | None]
    conflict: NotRequired[bool]
    result: NotRequired[DecisionResult]

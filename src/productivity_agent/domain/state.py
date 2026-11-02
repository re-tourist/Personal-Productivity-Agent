"""M1 contract. Keep raw domain data here, not prompts or serialized tool messages.

The student should inspect this state and justify each field. Later milestones
may introduce richer structured state, but preserve the business semantics.
"""

from typing import Literal, NotRequired, TypedDict


class TimeSlot(TypedDict):
    start_at: str  # Offset-aware ISO 8601; e.g. 2026-11-03T15:00:00+08:00
    end_at: str


class CalendarRequest(TimeSlot):
    title: str


class DecisionResult(TypedDict):
    status: Literal["invalid", "available", "conflict", "no_available_slot"]
    message: str
    suggested_start: NotRequired[str]
    suggested_end: NotRequired[str]


class CalendarState(TypedDict):
    request: CalendarRequest
    busy_slots: list[TimeSlot]  # M1 mock data; will be fetched by tools in M3
    error: NotRequired[str | None]
    conflict: NotRequired[bool]
    result: NotRequired[DecisionResult]

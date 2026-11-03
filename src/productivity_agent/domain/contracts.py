"""Framework-independent calendar data contracts."""
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

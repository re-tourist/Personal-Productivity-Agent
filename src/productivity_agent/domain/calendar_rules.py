"""Pure calendar business rules, separate from the LangGraph scheduler.

The MVP uses explicit UTC offsets and same-day, half-open intervals. No calendar
writes are performed here.  These functions can run without LLM dependencies.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Sequence

from productivity_agent.domain.policy import DEFAULT_POLICY, SchedulingPolicy
from productivity_agent.domain.state import CalendarRequest, TimeSlot
from productivity_agent.domain.time_utils import as_interval


def overlaps(left_start, left_end, right_start, right_end) -> bool:
    return left_start < right_end and right_start < left_end


def has_conflict(request: CalendarRequest, busy_slots: Sequence[TimeSlot]) -> bool:
    start, end = as_interval(request)
    return any(overlaps(start, end, *as_interval(busy)) for busy in busy_slots)


def next_available_slot(
    request: CalendarRequest,
    busy_slots: Sequence[TimeSlot],
    policy: SchedulingPolicy = DEFAULT_POLICY,
) -> dict | None:
    """Search *later* candidates in fixed steps ending before the daily cutoff.

    The candidate respects the user's selected UTC offset. This is a demo,
    not a substitute for an IANA-zone-aware calendar scheduling service.
    """
    if policy.search_step_minutes < 1:
        raise ValueError("search_step_minutes must be positive")
    start, end = as_interval(request)
    cutoff = start.replace(hour=policy.latest_end_hour, minute=0, second=0, microsecond=0)
    duration = end - start
    increment = timedelta(minutes=policy.search_step_minutes)
    candidate = start + increment
    while candidate + duration <= cutoff:
        candidate_end = candidate + duration
        if all(
            not overlaps(candidate, candidate_end, *as_interval(busy))
            for busy in busy_slots
        ):
            return {"start_at": candidate.isoformat(), "end_at": candidate_end.isoformat()}
        candidate += increment
    return None


def assess_calendar(request: CalendarRequest, busy_slots: Sequence[TimeSlot]) -> dict:
    """Return exactly the same decision contract as the M1 calendar graph."""
    try:
        if not isinstance(request["title"], str) or not request["title"].strip():
            raise ValueError("Schedule title must be non-empty")
        as_interval(request)
        for busy in busy_slots:
            as_interval(busy)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return {"status": "invalid", "message": str(exc)}

    if not has_conflict(request, busy_slots):
        return {"status": "available", "message": "No calendar conflict. Nothing has been created."}

    alternative = next_available_slot(request, busy_slots)
    if alternative is None:
        return {
            "status": "no_available_slot",
            "message": "No same-day alternative ends by the scheduling cutoff.",
        }
    return {
        "status": "conflict",
        "message": "Requested time is busy. An alternative is available; no event created.",
        "suggested_start": alternative["start_at"],
        "suggested_end": alternative["end_at"],
    }

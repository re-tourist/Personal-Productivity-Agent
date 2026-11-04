"""Read-only calendar execution, also used by the persisted Graph's steps.

The input envelope is ordinary request data, not Graph State. Keep the original
validation order/error text: domain.assess_calendar has a different non-string
title diagnostic and cannot silently replace this existing contract.
"""
from productivity_agent.application.ports.calendar import CalendarReader
from productivity_agent.domain.calendar_rules import has_conflict, next_available_slot
from productivity_agent.domain.contracts import CalendarRequest, TimeSlot
from productivity_agent.domain.time_utils import as_interval


def validation_error(inputs: dict) -> str | None:
    try:
        request = inputs["request"]
        if not request["title"].strip():
            raise ValueError("Schedule title must be non-empty")
        as_interval(request)
        for slot in inputs["busy_slots"]:
            as_interval(slot)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return str(exc)
    return None


def invalid_result(error: str | None) -> dict:
    return {"status": "invalid", "message": error or "Invalid request"}


def available_result() -> dict:
    return {"status": "available", "message": "No calendar conflict. Nothing has been created."}


def alternative_result(request: CalendarRequest, busy_slots: list[TimeSlot]) -> dict:
    candidate = next_available_slot(request, busy_slots)
    if candidate:
        return {
            "status": "conflict",
            "message": "Requested time is busy. An alternative is available; no event created.",
            "suggested_start": candidate["start_at"], "suggested_end": candidate["end_at"],
        }
    return {"status": "no_available_slot",
            "message": "No same-day alternative ends by the scheduling cutoff."}


def check_calendar(request: CalendarRequest, busy_slots: list[TimeSlot]) -> dict:
    error = validation_error({"request": request, "busy_slots": busy_slots})
    if error:
        return invalid_result(error)
    if has_conflict(request, busy_slots):
        return alternative_result(request, busy_slots)
    return available_result()


def calendar_events(reader: CalendarReader, date_iso: str) -> list[CalendarRequest]:
    return reader.events_on(date_iso)


def calendar_busy_slots(reader: CalendarReader) -> list[TimeSlot]:
    return reader.busy_slots()


def propose_calendar_replan(request: dict, busy_slots: list[dict]) -> dict:
    """Propose only; never authorize or create an event."""
    result = check_calendar(request, busy_slots)
    if result["status"] == "available":
        return {"status": "ready", "proposal": request, "requires_confirmation": False}
    if result["status"] == "conflict" and result.get("suggested_start"):
        return {
            "status": "needs_confirmation", "reason": "calendar_conflict",
            "proposal": {**request, "start_at": result["suggested_start"],
                         "end_at": result["suggested_end"]},
            "requires_confirmation": True,
        }
    return {"status": "unable_to_plan", "reason": result["status"],
            "proposal": None, "requires_confirmation": False}

"""M4 business replan: propose an alternative but never write without consent."""

from productivity_agent.workflows.calendar import build_graph as build_calendar_graph


def propose_calendar_replan(request: dict, busy_slots: list[dict]) -> dict:
    """Reuse M1 to re-plan a conflicting calendar action deterministically.

    The returned proposal is NOT an approved or created event.
    """
    result = build_calendar_graph().invoke({"request": request, "busy_slots": busy_slots})["result"]
    if result["status"] == "available":
        return {"status": "ready", "proposal": request, "requires_confirmation": False}
    if result["status"] == "conflict" and result.get("suggested_start"):
        return {
            "status": "needs_confirmation",
            "reason": "calendar_conflict",
            "proposal": {
                **request,
                "start_at": result["suggested_start"],
                "end_at": result["suggested_end"],
            },
            "requires_confirmation": True,
        }
    return {
        "status": "unable_to_plan", "reason": result["status"],
        "proposal": None, "requires_confirmation": False,
    }

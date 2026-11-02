"""M1 calendar regression tests, part of the full M7 CI test suite."""

from productivity_agent.workflows.calendar import build_graph, overlaps


def case(start="2026-11-03T15:00:00+08:00", end="2026-11-03T16:00:00+08:00", busy=None, title="组会"):
    return {
        "request": {"title": title, "start_at": start, "end_at": end},
        "busy_slots": [] if busy is None else busy,
    }


def slot(start, end):
    return {"start_at": start, "end_at": end}


def test_half_open_interval_overlap():
    assert overlaps(1, 3, 2, 4) is True
    assert overlaps(1, 2, 2, 3) is False
    assert overlaps(2, 3, 1, 2) is False


def test_available():
    result = build_graph().invoke(case())
    assert result["conflict"] is False
    assert result["result"]["status"] == "available"


def test_conflict_and_earliest_alternative():
    busy = [slot("2026-11-03T15:30:00+08:00", "2026-11-03T16:30:00+08:00")]
    result = build_graph().invoke(case(busy=busy))
    assert result["conflict"] is True
    assert result["result"]["status"] == "conflict"
    assert result["result"]["suggested_start"] == "2026-11-03T16:30:00+08:00"
    assert result["result"]["suggested_end"] == "2026-11-03T17:30:00+08:00"


def test_touching_endpoints_are_not_a_conflict():
    busy = [slot("2026-11-03T16:00:00+08:00", "2026-11-03T17:00:00+08:00")]
    result = build_graph().invoke(case(busy=busy))
    assert result["result"]["status"] == "available"


def test_invalid_end_time():
    result = build_graph().invoke(case(end="2026-11-03T14:00:00+08:00"))
    assert result["result"]["status"] == "invalid"


def test_missing_timezone():
    result = build_graph().invoke(case(start="2026-11-03T15:00:00"))
    assert result["result"]["status"] == "invalid"


def test_empty_title():
    result = build_graph().invoke(case(title="  "))
    assert result["result"]["status"] == "invalid"


def test_no_available_slot_before_1800():
    busy = [slot("2026-11-03T15:00:00+08:00", "2026-11-03T18:00:00+08:00")]
    result = build_graph().invoke(case(busy=busy))
    assert result["result"]["status"] == "no_available_slot"


def test_does_not_mutate_input_calendar():
    busy = [slot("2026-11-03T15:30:00+08:00", "2026-11-03T16:30:00+08:00")]
    data = case(busy=busy)
    original = [s.copy() for s in data["busy_slots"]]
    build_graph().invoke(data)
    assert data["busy_slots"] == original

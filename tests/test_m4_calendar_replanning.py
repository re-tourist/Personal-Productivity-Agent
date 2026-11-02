"""Replanning using the actual M1 calendar graph, without a real calendar account."""

from productivity_agent.workflows.calendar_replanning import propose_calendar_replan


def test_calendar_conflict_proposes_without_writing():
    requested = {
        "title": "组会", "start_at": "2026-11-03T15:00:00+08:00",
        "end_at": "2026-11-03T16:00:00+08:00",
    }
    existing = [{"start_at": "2026-11-03T15:30:00+08:00",
                 "end_at": "2026-11-03T16:30:00+08:00"}]
    result = propose_calendar_replan(requested, existing)
    assert result["status"] == "needs_confirmation"
    assert result["proposal"]["start_at"] == "2026-11-03T16:30:00+08:00"
    assert result["requires_confirmation"] is True

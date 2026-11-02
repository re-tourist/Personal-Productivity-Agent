"""M7 independent tests: do not require LangGraph or a live model."""

from productivity_agent.domain.calendar_rules import assess_calendar, next_available_slot
from productivity_agent.evaluation import run_evaluation
from productivity_agent.domain.policy import SchedulingPolicy


def test_offline_acceptance_suite_is_all_green():
    report = run_evaluation()
    assert report["total"] == 10
    assert report["passed"] == 10, report["cases"]
    assert report["failed"] == 0
    assert report["llm_calls"] == 0
    assert report["llm_cost_cny"] == 0


def test_calendar_search_policy_can_be_changed():
    request = {
        "title": "组会",
        "start_at": "2026-12-10T15:00:00+08:00",
        "end_at": "2026-12-10T16:00:00+08:00",
    }
    busy = [{"start_at": "2026-12-10T15:00:00+08:00", "end_at": "2026-12-10T15:20:00+08:00"}]
    got = next_available_slot(request, busy, SchedulingPolicy(search_step_minutes=15))
    assert got["start_at"] == "2026-12-10T15:30:00+08:00"
    assert assess_calendar(request, busy)["status"] == "conflict"


def test_invalid_slot_is_rejected_even_if_other_slots_do_not_overlap():
    request = {
        "title": "组会",
        "start_at": "2026-12-10T15:00:00+08:00",
        "end_at": "2026-12-10T16:00:00+08:00",
    }
    bad = [{"start_at": "2026-12-10T20:00:00+08:00", "end_at": "2026-12-10T19:00:00+08:00"}]
    assert assess_calendar(request, bad)["status"] == "invalid"

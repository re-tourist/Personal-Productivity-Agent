"""Offline end-to-end tests using a fake extractor, no model API required."""

from productivity_agent.domain.intent import ScheduleIntent
from productivity_agent.workflows.natural_language import build_natural_language_graph


class FakeExtractor:
    def __init__(self, intent):
        self.intent = intent

    def invoke(self, messages):
        assert messages[0][0] == "system"
        return self.intent


def inp():
    return {
        "user_text": "明天下午三点安排一个小时的组会",
        "reference_now": "2026-11-02T12:00:00+08:00",
        "busy_slots": [{
            "start_at": "2026-11-03T15:30:00+08:00",
            "end_at": "2026-11-03T16:30:00+08:00",
        }],
    }


def test_natural_language_graph_integrates_m1():
    graph = build_natural_language_graph(FakeExtractor(ScheduleIntent(
        action="schedule_event", title="组会",
        start_at="2026-11-03T15:00:00+08:00",
        duration_minutes=60, clarification_question=None,
    )))
    output = graph.invoke(inp())
    assert output["result"]["status"] == "conflict"
    assert output["result"]["suggested_start"] == "2026-11-03T16:30:00+08:00"


def test_missing_time_goes_to_clarification():
    graph = build_natural_language_graph(FakeExtractor(ScheduleIntent(
        action="schedule_event", title="组会", start_at=None,
        duration_minutes=60, clarification_question="什么时候开始？",
    )))
    output = graph.invoke(inp())
    assert output["result"]["status"] == "clarification_required"


def test_unsupported_request_is_not_executed():
    graph = build_natural_language_graph(FakeExtractor(ScheduleIntent(
        action="unsupported", title=None, start_at=None,
        duration_minutes=None, clarification_question=None,
    )))
    output = graph.invoke(inp())
    assert output["result"]["status"] == "unsupported"

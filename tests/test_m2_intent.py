from productivity_agent.domain.intent import ScheduleIntent, normalize_schedule_intent


def make_intent(**updates):
    fields = dict(
        action="schedule_event",
        title="组会",
        start_at="2026-11-03T15:00:00+08:00",
        duration_minutes=60,
        clarification_question=None,
    )
    fields.update(updates)
    return ScheduleIntent(**fields)


def test_valid_intent_is_m1_compatible():
    request, question = normalize_schedule_intent(make_intent(), "2026-11-02T12:00:00+08:00")
    assert question is None
    assert request == {
        "title": "组会",
        "start_at": "2026-11-03T15:00:00+08:00",
        "end_at": "2026-11-03T16:00:00+08:00",
    }


def test_missing_start_requests_clarification():
    request, question = normalize_schedule_intent(
        make_intent(start_at=None, clarification_question="几点开始？"),
        "2026-11-02T12:00:00+08:00",
    )
    assert request is None
    assert question == "几点开始？"


def test_invalid_duration_is_rejected():
    request, question = normalize_schedule_intent(
        make_intent(duration_minutes=-1),
        "2026-11-02T12:00:00+08:00",
    )
    assert request is None
    assert "1～480" in question


def test_past_time_requires_reprompt():
    request, question = normalize_schedule_intent(
        make_intent(start_at="2026-11-02T10:00:00+08:00"),
        "2026-11-02T12:00:00+08:00",
    )
    assert request is None
    assert "已过去" in question


def test_unsupported_action():
    request, question = normalize_schedule_intent(
        make_intent(action="unsupported"),
        "2026-11-02T12:00:00+08:00",
    )
    assert request is None
    assert question is not None

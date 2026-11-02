from datetime import datetime

import pytest

from productivity_agent.domain.policy import DEFAULT_POLICY
from productivity_agent.domain.time_utils import as_interval
from productivity_agent.demo_data import SAMPLE_CONFLICT_CASE


def test_sample_has_offset_aware_times():
    start, end = as_interval(SAMPLE_CONFLICT_CASE["request"])
    assert isinstance(start, datetime)
    assert start.utcoffset().total_seconds() == 8 * 3600
    assert end > start


def test_invalid_interval_is_rejected():
    with pytest.raises(ValueError):
        as_interval({"start_at": "2026-11-03T16:00:00+08:00", "end_at": "2026-11-03T15:00:00+08:00"})


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        as_interval({"start_at": "2026-11-03T15:00:00", "end_at": "2026-11-03T16:00:00"})


def test_policy_is_explicit_and_reproducible():
    assert DEFAULT_POLICY.search_step_minutes == 30
    assert DEFAULT_POLICY.latest_end_hour == 18

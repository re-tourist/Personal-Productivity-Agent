"""Shared reproducible sample case used by the CLI and docs."""

SAMPLE_CONFLICT_CASE = {
    "request": {
        "title": "组会",
        "start_at": "2026-11-03T15:00:00+08:00",
        "end_at": "2026-11-03T16:00:00+08:00",
    },
    "busy_slots": [
        {
            "start_at": "2026-11-03T15:30:00+08:00",
            "end_at": "2026-11-03T16:30:00+08:00",
        }
    ],
}


from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def make_tomorrow_conflict_case(reference_now: datetime | None = None) -> dict:
    """A future-dated live demo case; the fixed SAMPLE is kept for regression tests."""
    now = reference_now or datetime.now(ZoneInfo("Asia/Shanghai"))
    tomorrow = now + timedelta(days=1)
    start = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)
    return {
        "request": {
            "title": "组会", "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
        },
        "busy_slots": [{
            "start_at": (start + timedelta(minutes=30)).isoformat(),
            "end_at": (start + timedelta(minutes=90)).isoformat(),
        }],
    }

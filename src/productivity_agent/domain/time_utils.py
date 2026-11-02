"""Basic, deterministic time parsing. Important graph logic lives elsewhere."""

from datetime import datetime
from typing import Mapping


def as_interval(slot: Mapping[str, str]) -> tuple[datetime, datetime]:
    """Parse a half-open interval [start, end), with mandatory timezone offset."""
    try:
        start = datetime.fromisoformat(slot["start_at"])
        end = datetime.fromisoformat(slot["end_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid ISO 8601 time interval") from exc
    if start.tzinfo is None or end.tzinfo is None or start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("Both times must carry an explicit timezone offset")
    if end <= start:
        raise ValueError("End time must be later than start time")
    return start, end

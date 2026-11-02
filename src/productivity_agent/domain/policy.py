from dataclasses import dataclass


@dataclass(frozen=True)
class SchedulingPolicy:
    """Fixed-offset timezone, same-calendar-day MVP scheduling policy (M1)."""

    search_step_minutes: int = 30
    latest_end_hour: int = 18


DEFAULT_POLICY = SchedulingPolicy()

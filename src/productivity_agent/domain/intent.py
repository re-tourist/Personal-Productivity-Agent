"""Approved legacy Domain facade (2/3); M2 model contracts belong to Agent."""
from productivity_agent.application.agent.llm.contracts import ScheduleIntent
from productivity_agent.application.agent.llm.normalization import normalize_schedule_intent

__all__ = ["ScheduleIntent", "normalize_schedule_intent"]

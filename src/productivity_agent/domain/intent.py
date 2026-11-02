"""M2: Structured intent contract and deterministic business validation.

The LLM extracts parameters, but domain rules decide if execution is safe.
"""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from productivity_agent.domain.state import CalendarRequest


class ScheduleIntent(BaseModel):
    """Output schema for the LLM; each field is required but may be null."""

    action: Literal["schedule_event", "unsupported"] = Field(
        description="schedule_event for calendar scheduling; unsupported otherwise"
    )
    title: str | None = Field(description="Event title; null if unspecified")
    start_at: str | None = Field(
        description="ISO 8601 datetime with explicit UTC offset; null if unknown"
    )
    duration_minutes: int | None = Field(
        description="Duration in whole minutes; null if user did not provide it"
    )
    clarification_question: str | None = Field(
        description="Short question for missing or ambiguous details, otherwise null"
    )


def normalize_schedule_intent(
    intent: ScheduleIntent,
    reference_now: str,
) -> tuple[CalendarRequest | None, str | None]:
    """Convert parsed intent into validated M1 input, or request clarification.

    Dates use explicit fixed UTC offsets for this MVP. IANA timezone and DST
    handling belong in the later calendar integrations milestone.
    """
    if intent.action != "schedule_event":
        return None, "暂时只支持日程安排，请告诉我你希望安排的日程。"

    title = (intent.title or "").strip()
    if not title:
        return None, "这项日程叫什么名字？"
    if intent.start_at is None:
        return None, intent.clarification_question or "你希望什么时候开始？"
    if intent.duration_minutes is None:
        return None, "预计持续多少分钟？"
    if not 1 <= intent.duration_minutes <= 480:
        return None, "单次日程时长需要在 1～480 分钟之间。"

    try:
        start = datetime.fromisoformat(intent.start_at)
        now = datetime.fromisoformat(reference_now)
    except ValueError:
        return None, "开始时间格式无法识别，请提供明确的日期和时间。"

    if start.utcoffset() is None or now.utcoffset() is None:
        return None, "开始时间需要明确时区。"
    if start <= now:
        return None, "开始时间已过去，请提供一个未来时间。"

    end = start + timedelta(minutes=intent.duration_minutes)
    request: CalendarRequest = {
        "title": title,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
    }
    return request, None

"""M2 intent normalization, retaining the original fixed-offset rules."""
from datetime import datetime, timedelta

from productivity_agent.application.agent.llm.contracts import ScheduleIntent
from productivity_agent.domain.contracts import CalendarRequest


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

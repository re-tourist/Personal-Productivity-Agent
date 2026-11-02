"""Limited Chinese demo grammar, explicitly NOT an LLM or general NLP fallback."""
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from productivity_agent.domain.agent_intent import AgentIntent

NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def number(value: str) -> int:
    return int(value) if value.isdigit() else NUMBERS[value]


class OfflineIntentExtractor:
    def invoke(self, messages):
        context = json.loads(messages[-1][1])
        text = context["message"].strip(" 。！？")
        pending = context["pending"] or {}
        if "任务" in text and any(w in text for w in ["查看", "查询", "列出"]):
            return AgentIntent(action="list_tasks")
        if any(w in text for w in ["提醒我", "创建", "新建"]):
            action = "create_task"
            match = re.search(r"(?:提醒我|创建(?:一个)?|新建(?:一个)?)(.*)", text)
            title = re.sub(r"(?:的)?任务$", "", match[1]).strip() if match else None
        elif "安排" in text or "日程" in text:
            action = "check_calendar"
            match = re.search(r"安排(?:一个)?(?:[一二两\d]+个?小时|\d+分钟)?(?:的)?(.*)", text)
            title = match[1].strip() if match else None
        elif pending:
            action, title = pending["action"], pending.get("title")
        else:
            return AgentIntent(action="unsupported", question="离线模式支持创建任务、查询任务和日程检查。")
        now = datetime.fromisoformat(context["reference_now"]).astimezone(ZoneInfo(context["timezone"]))
        day = re.search(r"今天|明天|后天", text)
        clock = re.search(r"(上午|下午|晚上|中午|早上)?([一二两三四五六七八九十\d]+)点(半|\d{1,2}分?)?", text)
        at = pending.get("at")
        if day and clock:
            hour = number(clock[2])
            if clock[1] in ["下午", "晚上", "中午"] and hour < 12:
                hour += 12
            minute = 30 if clock[3] == "半" else int((clock[3] or "0").rstrip("分"))
            at = (now + timedelta(days={"今天": 0, "明天": 1, "后天": 2}[day[0]])).replace(
                hour=hour, minute=minute, second=0, microsecond=0).isoformat()
        duration = pending.get("duration_minutes")
        hours = re.search(r"([一二两三四五六七八九十\d]+)个?小时", text)
        minutes = re.search(r"(\d+)分钟", text)
        if hours:
            duration = number(hours[1]) * 60
        elif minutes:
            duration = int(minutes[1])
        return AgentIntent(action=action, title=title or None, at=at, duration_minutes=duration)

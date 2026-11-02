"""M3 tools backed by an explicitly in-memory mock system.

No real calendar, task service, or other external service is accessed.
All mutations are mock-only and omitted from the model's available tools by default.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from langchain_core.tools import tool

from productivity_agent.domain.state import CalendarRequest
from productivity_agent.workflows.calendar import build_graph as build_calendar_graph


@dataclass
class MockProductivityBackend:
    events: list[CalendarRequest] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)

    def events_on(self, date_iso: str) -> list[CalendarRequest]:
        target = date.fromisoformat(date_iso)
        return [event.copy() for event in self.events
                if datetime.fromisoformat(event["start_at"]).date() == target]

    def create_task(self, title: str, due_at: str) -> dict:
        title = title.strip()
        if not title:
            raise ValueError("任务标题不能为空")
        due = datetime.fromisoformat(due_at)
        if due.utcoffset() is None:
            raise ValueError("due_at 必须包含时区偏移")
        task = {"id": f"mock-task-{len(self.tasks) + 1}",
                "title": title, "due_at": due.isoformat()}
        self.tasks.append(task)
        return task.copy()


def build_productivity_tools(
    backend: MockProductivityBackend,
    *,
    allow_mock_writes: bool = False,
) -> list:
    """Return the tools the model is allowed to see and call."""
    calendar_graph = build_calendar_graph()

    @tool
    def list_calendar_events(date_iso: str) -> str:
        """查询某天的已有日程。date_iso 必须为 YYYY-MM-DD，例如 2026-11-03。"""
        return json.dumps(backend.events_on(date_iso), ensure_ascii=False)

    @tool
    def check_calendar_conflict(title: str, start_at: str, end_at: str) -> dict:
        """检查一个候选日程是否冲突，并在冲突时建议备选时间；不创建日程。时间必须含时区。"""
        request: CalendarRequest = {
            "title": title, "start_at": start_at, "end_at": end_at,
        }
        outcome = calendar_graph.invoke({
            "request": request,
            "busy_slots": [
                {"start_at": item["start_at"], "end_at": item["end_at"]}
                for item in backend.events
            ],
        })
        return outcome["result"]

    @tool
    def list_tasks() -> str:
        """查询模拟任务列表，不会调用真实业务服务。"""
        return json.dumps([item.copy() for item in backend.tasks], ensure_ascii=False)

    tools = [list_calendar_events, check_calendar_conflict, list_tasks]

    if allow_mock_writes:
        @tool
        def create_task(title: str, due_at: str) -> dict:
            """仅在用户允许的模拟模式下创建本地内存任务。due_at 是含时区的 ISO 8601 时间。"""
            task = backend.create_task(title, due_at)
            return {"status": "created_in_mock_only", "task": task}

        tools.append(create_task)

    return tools

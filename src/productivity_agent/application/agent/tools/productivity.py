"""Model tool adapters over explicit mock data; no persistent task binding."""
import json
from typing import Protocol

from langchain_core.tools import tool

from productivity_agent.application.agent.workflows.calendar import (
    build_graph as build_calendar_graph,
)
from productivity_agent.application.ports.calendar import CalendarReader
from productivity_agent.application.use_cases.calendar import calendar_busy_slots, calendar_events
from productivity_agent.domain.contracts import CalendarRequest


class MockToolBackend(CalendarReader, Protocol):
    """Demo-only capabilities, deliberately incompatible with persistent TaskReader."""
    def list_mock_tasks(self) -> list[dict]: ...
    def create_task(self, title: str, due_at: str) -> dict: ...


def build_productivity_tools(
    backend: MockToolBackend,
    *,
    allow_mock_writes: bool = False,
) -> list:
    """Return the tools the model is allowed to see and call."""
    calendar_graph = build_calendar_graph()

    @tool
    def list_calendar_events(date_iso: str) -> str:
        """查询某天的已有日程。date_iso 必须为 YYYY-MM-DD，例如 2026-11-03。"""
        return json.dumps(calendar_events(backend, date_iso), ensure_ascii=False)

    @tool
    def check_calendar_conflict(title: str, start_at: str, end_at: str) -> dict:
        """检查一个候选日程是否冲突，并在冲突时建议备选时间；不创建日程。时间必须含时区。"""
        request: CalendarRequest = {
            "title": title, "start_at": start_at, "end_at": end_at,
        }
        outcome = calendar_graph.invoke({
            "request": request,
            "busy_slots": calendar_busy_slots(backend),
        })
        return outcome["result"]

    @tool
    def list_tasks() -> str:
        """查询模拟任务列表，不会调用真实业务服务。"""
        return json.dumps(backend.list_mock_tasks(), ensure_ascii=False)

    tools = [list_calendar_events, check_calendar_conflict, list_tasks]

    if allow_mock_writes:
        @tool
        def create_task(title: str, due_at: str) -> dict:
            """仅在用户允许的模拟模式下创建本地内存任务。due_at 是含时区的 ISO 8601 时间。"""
            task = backend.create_task(title, due_at)
            return {"status": "created_in_mock_only", "task": task}

        tools.append(create_task)

    return tools

"""Explicit in-memory demo data; not the persistent task service."""
from dataclasses import dataclass, field
from datetime import date, datetime

from productivity_agent.domain.contracts import CalendarRequest, TimeSlot


@dataclass
class MockProductivityBackend:
    events: list[CalendarRequest] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)

    def events_on(self, date_iso: str) -> list[CalendarRequest]:
        target = date.fromisoformat(date_iso)
        return [event.copy() for event in self.events
                if datetime.fromisoformat(event["start_at"]).date() == target]

    def busy_slots(self) -> list[TimeSlot]:
        return [{"start_at": event["start_at"], "end_at": event["end_at"]}
                for event in self.events]

    def list_mock_tasks(self) -> list[dict]:
        return [item.copy() for item in self.tasks]

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



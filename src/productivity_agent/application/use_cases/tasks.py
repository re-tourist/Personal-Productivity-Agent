"""Shared reads; protocol-specific limits and missing-resource mapping stay outside."""
from productivity_agent.application.ports.tasks import TaskReader


def list_tasks(reader: TaskReader, *, limit: int = 100) -> list[dict]:
    return reader.list_tasks(limit=limit)


def get_task(reader: TaskReader, task_id: str) -> dict:
    return reader.get_task(task_id)


def get_operation(reader: TaskReader, operation_id: str) -> dict | None:
    return reader.get_operation(operation_id)

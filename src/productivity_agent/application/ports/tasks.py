"""Synchronous task reads in an already trusted owner scope.

Missing/inaccessible tasks raise KeyError. A successful operation read may return
None; unavailable reads must propagate. Creation receipts describe the current
task, while change receipts can be historical. No credentials or write methods.
"""
from typing import Protocol


class TaskReader(Protocol):
    def list_tasks(self, *, limit: int = 100) -> list[dict]: ...
    def get_task(self, task_id: str) -> dict: ...
    def get_operation(self, operation_id: str) -> dict | None: ...

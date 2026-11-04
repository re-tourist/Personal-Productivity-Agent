"""Synchronous task reads in an already trusted owner scope.

Missing/inaccessible tasks raise KeyError. A successful operation read may return
None; unavailable reads must propagate. Creation receipts describe the current
task, while change receipts can be historical. No credentials or owner selection.
"""
from typing import Protocol


class TaskReader(Protocol):
    def list_tasks(self, *, limit: int = 100) -> list[dict]: ...
    def get_task(self, task_id: str) -> dict: ...
    def get_operation(self, operation_id: str) -> dict | None: ...


class TransientWriteError(ConnectionError):
    """Temporary failure before the transaction committed."""


class AmbiguousCommitError(TimeoutError):
    """A write may have committed; reconcile the same operation before retrying."""


class TaskCreator(Protocol):
    """Trusted, owner-bound creation and request-matched reconciliation.

    Same operation/request must have one business effect. lookup returns the
    current task, not an immutable creation receipt. None is a successful read
    with no visible operation; unavailable/unknown reads must raise.

    ValueError/IdempotencyConflict are permanent. HTTP 409 remains VersionConflict
    (a ValueError); HTTP reconciliation BusinessUnavailable still propagates.
    Legacy SQLite OperationalError/ConnectionError classification is preserved
    by the execution policy, without promising that any such error is pre-commit.
    Fault injection, credentials, owner selection and changes are not this Port.
    Authorization belongs to the trusted caller, never to model-provided fields.
    """

    def create_task(self, operation_id: str, title: str, due_at: str) -> dict: ...
    def lookup(self, operation_id: str, title: str, due_at: str) -> dict | None: ...

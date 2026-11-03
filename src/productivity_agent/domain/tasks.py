"""Task business conflicts and deterministic request validation; no storage or graph dependency."""
from datetime import UTC, datetime


class IdempotencyConflict(ValueError):
    """An operation id was reused with different business parameters."""


class VersionConflict(ValueError):
    """The approved snapshot is stale; read again and obtain fresh approval."""


def validate_task_request(operation_id: str, title: str, due_at: str) -> tuple[str, str, str]:
    if not isinstance(operation_id, str) or not 0 < len(operation_id.strip()) <= 128:
        raise ValueError("operation_id must be a nonempty string up to 128 chars")
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 200:
        raise ValueError("title must be a nonempty string up to 200 chars")
    try:
        due = datetime.fromisoformat(due_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("due_at must be an ISO 8601 date-time") from exc
    if due.utcoffset() is None:
        raise ValueError("due_at must have a timezone offset")
    # Canonicalize the same instant to avoid false conflicts from timezone representations.
    due_utc = due.astimezone(UTC).isoformat()
    return operation_id.strip(), title.strip(), due_utc

"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.persistence.task_store import (
    AmbiguousCommitError,
    IdempotencyConflict,
    OwnedTaskStore,
    SQLiteTaskStore,
    TransientWriteError,
    VersionConflict,
    request_fingerprint,
    validate_task_request,
)

__all__ = ['AmbiguousCommitError', 'IdempotencyConflict', 'OwnedTaskStore', 'SQLiteTaskStore', 'TransientWriteError', 'VersionConflict', 'request_fingerprint', 'validate_task_request']

"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.integrations.http_task_store import (
    BusinessUnavailable,
    HTTPTaskStore,
)

__all__ = ['BusinessUnavailable', 'HTTPTaskStore']

"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.observability.operation_trace import (
    configure_logging,
    trace_context,
    traced_node,
)

__all__ = ['configure_logging', 'trace_context', 'traced_node']

"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.interfaces.http.routes.assistant import (
    assistant_router,
    config,
    view,
)
from productivity_agent.interfaces.http.schemas import (
    ApprovalRequest,
    MessageRequest,
)

__all__ = ['ApprovalRequest', 'MessageRequest', 'assistant_router', 'config', 'view']

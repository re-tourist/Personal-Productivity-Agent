"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.interfaces.http.assistant_app import (
    create_app,
)
from productivity_agent.interfaces.http.dependencies import (
    _check_token,
)
from productivity_agent.interfaces.http.routes.drafts import (
    _snapshot_response,
    _thread_config,
)
from productivity_agent.interfaces.http.schemas import (
    AgentQueryRequest,
    CalendarCheckRequest,
    CalendarRequestBody,
    CalendarSlot,
    DecisionRequest,
    NaturalLanguageCalendarRequest,
    StrictModel,
    TaskDraftRequest,
)
from productivity_agent.interfaces.http.streaming import (
    _encode_sse,
)

__all__ = ['AgentQueryRequest', 'CalendarCheckRequest', 'CalendarRequestBody', 'CalendarSlot', 'DecisionRequest', 'NaturalLanguageCalendarRequest', 'StrictModel', 'TaskDraftRequest', '_check_token', '_encode_sse', '_snapshot_response', '_thread_config', 'create_app']

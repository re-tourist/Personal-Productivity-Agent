"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.models.offline_intent import (
    NUMBERS,
    OfflineIntentExtractor,
    number,
    operation_intent,
    parse_operation_time,
)

__all__ = ['NUMBERS', 'OfflineIntentExtractor', 'number', 'operation_intent', 'parse_operation_time']

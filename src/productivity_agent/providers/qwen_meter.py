"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.observability.qwen_meter import (
    QwenMeter,
    QwenValidationError,
    ValidationBudget,
)

__all__ = ['QwenMeter', 'QwenValidationError', 'ValidationBudget']

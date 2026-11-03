"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.models.qwen import (
    DEFAULT_BEIJING_BASE_URL,
    DEFAULT_QWEN_MODEL,
    build_qwen_model,
)

__all__ = ['DEFAULT_BEIJING_BASE_URL', 'DEFAULT_QWEN_MODEL', 'build_qwen_model']

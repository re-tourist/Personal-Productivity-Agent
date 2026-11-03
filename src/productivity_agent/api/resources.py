"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.interfaces.http.dependencies import (
    resources_for,
)

__all__ = ['resources_for']

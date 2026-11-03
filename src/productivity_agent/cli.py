"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.interfaces.cli import (
    main,
)

__all__ = ['main']

"""Legacy M3 exports; one implementation and one mock data source (R2-B1)."""
from productivity_agent.application.agent.tools.productivity import build_productivity_tools
from productivity_agent.infrastructure.integrations.mock_productivity import MockProductivityBackend

__all__ = ["MockProductivityBackend", "build_productivity_tools"]

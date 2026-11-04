"""Legacy M2 exports, retained through R2 migration."""
from productivity_agent.application.agent.workflows.natural_language import (
    NaturalLanguageState,
    build_natural_language_graph,
)
from productivity_agent.application.ports.llm import StructuredExtractor

__all__ = ["NaturalLanguageState", "StructuredExtractor", "build_natural_language_graph"]

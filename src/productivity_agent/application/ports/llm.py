"""Existing structured model boundary; no SDK, credentials, or write authority."""
from typing import Protocol, TypeVar

IntentT_co = TypeVar("IntentT_co", covariant=True)


class StructuredExtractor(Protocol[IntentT_co]):
    def invoke(self, messages: list[tuple[str, str]]) -> IntentT_co: ...

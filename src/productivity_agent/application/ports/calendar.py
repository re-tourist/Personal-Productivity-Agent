"""Display filtering and conflict scope are separate calendar capabilities."""
from typing import Protocol

from productivity_agent.domain.contracts import CalendarRequest, TimeSlot


class CalendarReader(Protocol):
    def events_on(self, date_iso: str) -> list[CalendarRequest]: ...
    def busy_slots(self) -> list[TimeSlot]:
        """All conflict intervals, including events starting on other dates."""
        ...

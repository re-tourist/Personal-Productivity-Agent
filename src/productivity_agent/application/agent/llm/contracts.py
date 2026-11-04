"""M2 structured output contract; field descriptions/defaults are frozen."""
from typing import Literal

from pydantic import BaseModel, Field


class ScheduleIntent(BaseModel):
    """Output schema for the LLM; each field is required but may be null."""

    action: Literal["schedule_event", "unsupported"] = Field(
        description="schedule_event for calendar scheduling; unsupported otherwise"
    )
    title: str | None = Field(description="Event title; null if unspecified")
    start_at: str | None = Field(
        description="ISO 8601 datetime with explicit UTC offset; null if unknown"
    )
    duration_minutes: int | None = Field(
        description="Duration in whole minutes; null if user did not provide it"
    )
    clarification_question: str | None = Field(
        description="Short question for missing or ambiguous details, otherwise null"
    )

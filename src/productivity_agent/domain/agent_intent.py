"""Intent contract shared by online structured Qwen and the limited offline demo."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class AgentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create_task", "check_calendar", "list_tasks", "unsupported"]
    title: str | None = Field(default=None, max_length=200)
    at: AwareDatetime | None = Field(default=None, description="明确时区的日期时间；未知填 null")
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    question: str | None = Field(default=None, max_length=300)

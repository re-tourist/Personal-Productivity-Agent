"""Existing HTTP wire contracts. No schema redesign in R1."""
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarSlot(StrictModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def _valid_interval(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CalendarRequestBody(CalendarSlot):
    title: str = Field(min_length=1, max_length=200)


class CalendarCheckRequest(StrictModel):
    request: CalendarRequestBody
    busy_slots: list[CalendarSlot] = Field(default_factory=list, max_length=1000)

    def to_graph_input(self) -> dict:
        return {
            "request": {
                "title": self.request.title,
                "start_at": self.request.start_at.isoformat(),
                "end_at": self.request.end_at.isoformat(),
            },
            "busy_slots": [
                {"start_at": x.start_at.isoformat(), "end_at": x.end_at.isoformat()}
                for x in self.busy_slots
            ],
        }


class NaturalLanguageCalendarRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    reference_now: AwareDatetime
    busy_slots: list[CalendarSlot] = Field(default_factory=list, max_length=1000)


class TaskDraftRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime

    @field_validator("title")
    @classmethod
    def _no_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return value.strip()


class DecisionRequest(StrictModel):
    approved: bool


class AgentQueryRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    reference_now: AwareDatetime


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    reference_now: AwareDatetime
    timezone: str = "Asia/Shanghai"
    message_id: uuid.UUID

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: StrictBool
    operation_id: uuid.UUID


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    approved: StrictBool


class CreateRequest(WriteRequest):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime


class ChangeRequest(WriteRequest):
    expected_version: int = Field(ge=1, strict=True)
    action: str
    title: str | None = None
    due_at: AwareDatetime | None = None

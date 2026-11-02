"""Intent contract shared by online structured Qwen and the limited offline demo."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class AgentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create_task", "check_calendar", "list_tasks", "unsupported"] = Field(
        description="提醒/待办选create_task；检查能否安排日程选check_calendar；查待办选list_tasks")
    title: str | None = Field(default=None, max_length=200, description="任务或日程标题，例如组会；不要包含日期时间")
    at: AwareDatetime | None = Field(default=None, description=
        "create_task的到期时间或check_calendar的开始时间。按reference_now和timezone换算相对日期，输出带UTC偏移的ISO8601；确实未指定才填null")
    duration_minutes: int | None = Field(default=None, ge=1, le=480, description=
        "日程持续分钟数，例如一小时=60；用户未指定则null，不能猜测")
    question: str | None = Field(default=None, max_length=300, description=
        "只有必要参数缺失或确有歧义时才追问，信息完整则null")

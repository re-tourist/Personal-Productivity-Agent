"""Intent contract shared by online structured Qwen and the limited offline demo."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class AgentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create_task", "check_calendar", "list_tasks", "get_task", "update_task", "complete_task", "unsupported"] = Field(
        description="创建待办create_task；日程check_calendar；列表list_tasks；详情get_task；修改update_task；完成complete_task；操作缺参或指代不明仍保留动作并追问，不是unsupported")
    title: str | None = Field(default=None, max_length=200, description="实际原任务/日程标题；日期或指代描述不是标题，按时间定位时填null")
    at: AwareDatetime | None = Field(default=None, description=
        "create_task的到期时间、update_task修改后的新到期时间或check_calendar开始时间。只要新时间明确就必须提取，不能因目标未消歧而填null。按reference_now和timezone换算，输出带UTC偏移ISO8601")
    duration_minutes: int | None = Field(default=None, ge=1, le=480, description=
        "日程持续分钟数，例如一小时=60；用户未指定则null，不能猜测")
    question: str | None = Field(default=None, max_length=300, description=
        "只有必要参数缺失或确有歧义时才追问，信息完整则null")

    task_id: str | None = Field(default=None, max_length=128, description="明确目标任务ID；不得编造")
    new_title: str | None = Field(default=None, max_length=200, description="修改后的标题；title是原目标标题")
    target_at: AwareDatetime | None = Field(default=None, description="明确描述的原到期时间，须根据target_time_text换算；即使没有标题或ID也提取；不能用历史猜测。at是新时间")
    target_time_text: str | None = Field(default=None, max_length=200, description="当前用户消息中明确描述原到期时间的逐字引文；不能从历史补造；没有则null")
    new_time_text: str | None = Field(default=None, max_length=200, description="修改后时间的原文；多轮消歧时保留pending的新时间原文，不能将其当原时间")

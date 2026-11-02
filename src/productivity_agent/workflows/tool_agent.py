"""M3 ReAct tool loop with M4 opt-in reliable extra tools.

Backward compatible with M3 defaults; does not enable any write tool implicitly.
"""

from typing import NotRequired, Sequence

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from productivity_agent.tools.productivity import MockProductivityBackend, build_productivity_tools


class ToolAgentState(MessagesState):
    reference_now: str
    llm_calls: NotRequired[int]


SYSTEM_PROMPT = """你是 Personal Productivity Agent 的工具执行助手。
当前时间（含时区）：{reference_now}。
先判断用户实际要求，必要时调用已提供的工具。
查询已有日程：list_calendar_events；检查日程冲突：check_calendar_conflict；查询任务：list_tasks。
相对日期需转为带时区的绝对日期；不明确的参数必须追问，不能编造。
工具返回错误或数据不足时，说明限制，不得编造成功结果。
只有明确提供 create_task 工具且用户明确要求创建时，才可以操作本地模拟任务。
create_task 工具若返回 failed 或 needs_review，不得声称创建成功。
模拟工具不连接真实日历/任务账户，最后回答必须如实说明。
"""


def build_tool_agent(
    model,
    backend: MockProductivityBackend,
    *,
    allow_mock_writes: bool = False,
    max_model_calls: int = 4,
    extra_tools: Sequence = (),
):
    if max_model_calls < 1:
        raise ValueError("max_model_calls 必须至少为 1")
    tools = build_productivity_tools(backend, allow_mock_writes=allow_mock_writes)
    tools.extend(extra_tools)
    names = [t.name for t in tools]
    if len(names) != len(set(names)):
        raise ValueError("duplicate tool names (do not combine two create_task tools)")
    model_with_tools = model.bind_tools(tools)

    def call_model(state: ToolAgentState) -> dict:
        n = state.get("llm_calls", 0)
        if n >= max_model_calls:
            return {"messages": [AIMessage(
                content="已达到本次任务的模型调用上限，无法确认任务全部完成。"
            )]}
        messages = [
            SystemMessage(content=SYSTEM_PROMPT.format(reference_now=state["reference_now"])),
            *state["messages"],
        ]
        response = model_with_tools.invoke(messages)
        if len(getattr(response, "tool_calls", [])) > 2:
            response = AIMessage(content="单轮工具调用超过安全上限，未执行这些操作。")
        return {"messages": [response], "llm_calls": n + 1}

    builder = StateGraph(ToolAgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()

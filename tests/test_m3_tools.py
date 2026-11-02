"""Offline M3 tests, zero Qwen API calls."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from productivity_agent.tools.productivity import MockProductivityBackend, build_productivity_tools
from productivity_agent.workflows.tool_agent import build_tool_agent


class FakeChatModel:
    def __init__(self, tool_name: str, args: dict):
        self.tool_name = tool_name
        self.args = args
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = {tool.name for tool in tools}
        return self

    def invoke(self, messages):
        if any(isinstance(msg, ToolMessage) for msg in messages):
            return AIMessage(content="工具执行完成，已根据结果回复。")
        return AIMessage(content="", tool_calls=[{
            "name": self.tool_name, "args": self.args, "id": "fake_call_1", "type": "tool_call",
        }])


def initial_state():
    return {
        "messages": [HumanMessage(content="请查询我的日程")],
        "reference_now": "2026-11-02T12:00:00+08:00",
    }


def test_agent_calls_a_tool_and_observes_result():
    backend = MockProductivityBackend(events=[{
        "title": "组会",
        "start_at": "2026-11-03T15:30:00+08:00",
        "end_at": "2026-11-03T16:30:00+08:00",
    }])
    fake = FakeChatModel("list_calendar_events", {"date_iso": "2026-11-03"})
    out = build_tool_agent(fake, backend).invoke(initial_state())
    assert out["llm_calls"] == 2
    tool_messages = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "组会" in str(tool_messages[0].content)
    assert "create_task" not in fake.bound_tools


def test_calendar_check_reuses_m1():
    backend = MockProductivityBackend(events=[{
        "title": "已有组会",
        "start_at": "2026-11-03T15:30:00+08:00",
        "end_at": "2026-11-03T16:30:00+08:00",
    }])
    tools = {tool.name: tool for tool in build_productivity_tools(backend)}
    decision = tools["check_calendar_conflict"].invoke({
        "title": "新组会",
        "start_at": "2026-11-03T15:00:00+08:00",
        "end_at": "2026-11-03T16:00:00+08:00",
    })
    assert decision["status"] == "conflict"
    assert decision["suggested_start"] == "2026-11-03T16:30:00+08:00"


def test_mock_write_requires_explicit_opt_in():
    backend = MockProductivityBackend()
    readonly = {t.name for t in build_productivity_tools(backend)}
    assert "create_task" not in readonly
    enabled = {t.name: t for t in build_productivity_tools(backend, allow_mock_writes=True)}
    output = enabled["create_task"].invoke({
        "title": "准备组会",
        "due_at": "2026-11-03T14:30:00+08:00",
    })
    assert output["status"] == "created_in_mock_only"
    assert len(backend.tasks) == 1


def test_model_call_budget_is_bounded():
    fake = FakeChatModel("list_tasks", {})
    backend = MockProductivityBackend()
    out = build_tool_agent(fake, backend, max_model_calls=1).invoke(initial_state())
    assert out["llm_calls"] == 1
    assert "调用上限" in out["messages"][-1].content

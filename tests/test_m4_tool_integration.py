"""M4 tool integration into existing M3 Agent, no API charges."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from productivity_agent.services.task_store import SQLiteTaskStore
from productivity_agent.tools.productivity import MockProductivityBackend
from productivity_agent.tools.reliable_task import build_safe_create_task_tool
from productivity_agent.workflows.tool_agent import build_tool_agent


class FakeModel:
    def bind_tools(self, tools):
        self.names = {t.name for t in tools}
        return self

    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="我已读取工具结果。")
        return AIMessage(content="", tool_calls=[{
            "name": "create_task", "args": {
                "title": "准备组会", "due_at": "2026-11-03T15:00:00+08:00",
            }, "id": "llm-call-1", "type": "tool_call",
        }])


def test_m3_agent_can_use_reliable_m4_write_tool(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    write_tool = build_safe_create_task_tool(store, "trusted-operation-001")
    fake = FakeModel()
    graph = build_tool_agent(fake, MockProductivityBackend(), extra_tools=[write_tool])
    input_state = {
        "messages": [HumanMessage(content="创建一个模拟任务")],
        "reference_now": "2026-11-02T12:00:00+08:00",
    }
    first = graph.invoke(input_state)
    second = graph.invoke(input_state)
    assert "create_task" in fake.names
    assert store.count_tasks() == 1
    assert any(isinstance(m, ToolMessage) for m in first["messages"])
    assert any(isinstance(m, ToolMessage) for m in second["messages"])

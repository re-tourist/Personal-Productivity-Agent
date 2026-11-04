"""M3 live Qwen demo. Network calls consume paid tokens; tools are mocks."""

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage

from productivity_agent.application.agent.workflows.tool_agent import build_tool_agent
from productivity_agent.infrastructure.integrations.mock_productivity import MockProductivityBackend
from productivity_agent.infrastructure.models.qwen import build_qwen_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen + LangGraph mock tools demo")
    parser.add_argument("--allow-mock-writes", action="store_true",
                        help="Expose an in-memory-only create_task tool; no real external writes")
    parser.add_argument("--message", default="帮我查询明天的日程，以及目前有哪些待办任务")
    args = parser.parse_args()
    load_dotenv()

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    tomorrow = now + timedelta(days=1)
    backend = MockProductivityBackend(events=[{
        "title": "已有组会",
        "start_at": tomorrow.replace(hour=15, minute=30, second=0, microsecond=0).isoformat(),
        "end_at": tomorrow.replace(hour=16, minute=30, second=0, microsecond=0).isoformat(),
    }])
    model = build_qwen_model()
    graph = build_tool_agent(model, backend, allow_mock_writes=args.allow_mock_writes)
    result = graph.invoke({
        "messages": [HumanMessage(content=args.message)],
        "reference_now": now.isoformat(),
    }, config={"recursion_limit": 14})

    print("--- Execution trace (no API key shown) ---")
    for message in result["messages"]:
        if getattr(message, "tool_calls", None):
            print("tool calls:", [(call["name"], call["args"]) for call in message.tool_calls])
        elif isinstance(message, ToolMessage):
            print("tool result:", message.name, str(message.content)[:500])
    print("--- Final answer ---")
    print(result["messages"][-1].content)
    print("Model calls:", result["llm_calls"])
    print("Mock task count:", len(backend.tasks))


if __name__ == "__main__":
    main()

"""M4 demo: fault injection is offline. --live incurs Qwen API token charges."""

import argparse
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from productivity_agent.services.task_store import SQLiteTaskStore
from productivity_agent.workflows.reliable_task import build_reliable_task_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="PPA M4 retry and idempotency demo")
    parser.add_argument("--db-path", type=Path, default=Path(".ppa-data/tasks.sqlite3"))
    parser.add_argument("--operation-id", default=None, help="Reuse the same value to prove idempotency")
    parser.add_argument("--fault", choices=["none", "before_commit", "after_commit"],
                        default="after_commit", help="Inject only into first attempt")
    parser.add_argument("--live", action="store_true", help="Use real Qwen API (paid)")
    args = parser.parse_args()

    store = SQLiteTaskStore(args.db_path)
    operation_id = args.operation_id or str(uuid.uuid4())
    due_at = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0
    ).isoformat()
    if not args.live:
        graph = build_reliable_task_graph(
            store, fault_plan={1: args.fault} if args.fault != "none" else {},
        )
        out = graph.invoke({
            "operation_id": operation_id,
            "title": "准备组会",
            "due_at": due_at,
            "max_attempts": 3,
        })
        print(json.dumps({
            "status": out["status"],
            "attempts": out.get("attempts", 0),
            "task": out.get("task"),
            "error": out.get("error"),
            "task_count": store.count_tasks(),
            "operation_id": operation_id,
        }, ensure_ascii=False, indent=2))
        return

    # Live mode is opt-in. The operation id is created by our application, never by Qwen.
    from dotenv import load_dotenv
    from langchain_core.messages import HumanMessage, ToolMessage
    from productivity_agent.providers.qwen import build_qwen_model
    from productivity_agent.tools.productivity import MockProductivityBackend
    from productivity_agent.tools.reliable_task import build_safe_create_task_tool
    from productivity_agent.workflows.tool_agent import build_tool_agent

    load_dotenv()
    op_id = operation_id
    tool = build_safe_create_task_tool(store, operation_id=op_id)
    model = build_qwen_model()
    graph = build_tool_agent(model, MockProductivityBackend(), extra_tools=[tool])
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    result = graph.invoke({
        "messages": [HumanMessage(content=f"请创建一个明天15点准备组会的模拟待办任务。当前时间为 {now.isoformat()}")],
        "reference_now": now.isoformat(),
    }, config={"recursion_limit": 14})
    for message in result["messages"]:
        if isinstance(message, ToolMessage):
            print("tool result:", str(message.content)[:800])
    print("final:", result["messages"][-1].content)
    print("operation_id:", op_id, "sqlite_task_count:", store.count_tasks())


if __name__ == "__main__":
    main()

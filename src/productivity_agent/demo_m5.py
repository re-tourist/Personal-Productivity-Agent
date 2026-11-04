"""M5 CLI: run start/approve/reject in separate Python processes.

Examples:
  python -m productivity_agent.demo_m5 start --thread-id demo-01 --title 组会 --due-at 2026-12-10T15:00:00+08:00
  python -m productivity_agent.demo_m5 status --thread-id demo-01
  python -m productivity_agent.demo_m5 approve --thread-id demo-01
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from productivity_agent.application.agent.workflows.approval_session import build_approval_graph
from productivity_agent.services.task_store import SQLiteTaskStore


def main():
    parser = argparse.ArgumentParser(description="PPA M5 human approval and durable resume")
    parser.add_argument("action", choices=["start", "status", "approve", "reject"])
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--title", default="准备组会")
    parser.add_argument("--due-at", default="2026-12-10T15:00:00+08:00")
    parser.add_argument("--operation-id", default=None)
    parser.add_argument("--data-dir", default=".ppa-data")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteTaskStore(data_dir / "tasks.sqlite")
    config = {"configurable": {"thread_id": args.thread_id}}

    with SqliteSaver.from_conn_string(str(data_dir / "m5-checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        snapshot = graph.get_state(config)

        if args.action == "start":
            if snapshot.values:
                parser.error("thread 已有状态。一个任务使用独立 thread-id；审批请用 approve/reject")
            outcome = graph.invoke({
                "operation_id": args.operation_id or str(uuid.uuid4()),
                "title": args.title,
                "due_at": args.due_at,
            }, config=config)
            print(json.dumps({
                "state": "waiting" if "__interrupt__" in outcome else "finished",
                "interrupts": [x.value for x in outcome.get("__interrupt__", [])],
                "task_count": store.count_tasks(),
            }, ensure_ascii=False, indent=2))
            return

        if not snapshot.values:
            parser.error("thread 不存在。请先 start")

        if args.action == "status":
            print(json.dumps({
                "next": snapshot.next,
                "state": snapshot.values,
                "task_count": store.count_tasks(),
            }, ensure_ascii=False, indent=2))
            return

        if "approval" not in snapshot.next:
            parser.error("这个 thread 当前不在等待人工确认的状态")
        result = graph.invoke(Command(resume=(args.action == "approve")), config=config)
        print(json.dumps({
            "state": result,
            "task_count": store.count_tasks(),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

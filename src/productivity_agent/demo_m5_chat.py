"""M5 offline chat memory across independent process invocations."""

from __future__ import annotations

import argparse
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from productivity_agent.workflows.chat_memory import build_chat_memory_graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--data-dir", default=".ppa-data")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    config = {"configurable": {"thread_id": args.thread_id}}

    # Dedicated checkpoint DB because the approval and chat demos use different state schemas.
    with SqliteSaver.from_conn_string(str(data_dir / "m5-chat-checkpoints.sqlite")) as saver:
        graph = build_chat_memory_graph(saver)
        result = graph.invoke({"messages": [{"role": "user", "content": args.message}]}, config)
        print(result["messages"][-1].content)
        print(f"当前 Thread 消息总数：{len(result['messages'])}")


if __name__ == "__main__":
    main()

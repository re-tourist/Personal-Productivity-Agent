"""M5: offline conversation-memory teaching graph (no API calls)."""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph


def build_chat_memory_graph(checkpointer):
    def echo(state: MessagesState) -> dict:
        user_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
        latest = user_messages[-1].content if user_messages else ""
        return {"messages": [AIMessage(content=f"收到第 {len(user_messages)} 条用户消息：{latest}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("echo", echo)
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    return builder.compile(checkpointer=checkpointer)

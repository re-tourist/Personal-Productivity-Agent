from langgraph.checkpoint.sqlite import SqliteSaver

from productivity_agent.workflows.chat_memory import build_chat_memory_graph


def test_chat_history_same_thread_and_isolation(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / "chat.sqlite")) as saver:
        graph = build_chat_memory_graph(saver)
        cfg_a = {"configurable": {"thread_id": "a"}}
        cfg_b = {"configurable": {"thread_id": "b"}}
        first = graph.invoke({"messages": [("user", "早上好")]}, cfg_a)
        assert len(first["messages"]) == 2
        second = graph.invoke({"messages": [("user", "今天有什么安排？")]}, cfg_a)
        assert len(second["messages"]) == 4
        other = graph.invoke({"messages": [("user", "另一会话")]}, cfg_b)
        assert len(other["messages"]) == 2


def test_chat_history_survives_restart(tmp_path):
    db = tmp_path / "chat.sqlite"
    cfg = {"configurable": {"thread_id": "resume-chat"}}
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_chat_memory_graph(saver)
        graph.invoke({"messages": [("user", "第一条")]}, cfg)
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_chat_memory_graph(saver)
        assert len(graph.get_state(cfg).values["messages"]) == 2
        assert len(graph.invoke({"messages": [("user", "第二条")]}, cfg)["messages"]) == 4

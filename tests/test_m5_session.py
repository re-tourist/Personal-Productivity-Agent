"""M5 online framework tests: no LLM calls and no external APIs."""

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from productivity_agent.services.task_store import SQLiteTaskStore
from productivity_agent.workflows.approval_session import build_approval_graph


def data():
    return {
        "operation_id": "m5-op-001", "title": "准备组会",
        "due_at": "2026-12-10T15:00:00+08:00",
    }


def config(thread):
    return {"configurable": {"thread_id": thread}}


def test_pause_without_side_effect_then_approve(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        result = graph.invoke(data(), config("t1"))
        assert "__interrupt__" in result
        assert store.count_tasks() == 0
        snap = graph.get_state(config("t1"))
        assert "approval" in snap.next
        assert snap.values["status"] == "awaiting_approval"
        output = graph.invoke(Command(resume=True), config("t1"))
        assert output["status"] == "created"
        assert store.count_tasks() == 1
        assert graph.get_state(config("t1")).next == ()


def test_reject_does_not_write(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        graph.invoke(data(), config("rejected"))
        output = graph.invoke(Command(resume=False), config("rejected"))
        assert output["status"] == "cancelled"
        assert store.count_tasks() == 0


def test_restart_restores_pending_approval(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    db = tmp_path / "checkpoints.sqlite"
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_approval_graph(store, saver)
        assert "__interrupt__" in graph.invoke(data(), config("restart"))
    # New saver and graph simulate a separate process.
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_approval_graph(store, saver)
        assert "approval" in graph.get_state(config("restart")).next
        assert graph.invoke(Command(resume=True), config("restart"))["status"] == "created"
        assert store.count_tasks() == 1


def test_two_threads_same_operation_are_idempotent(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        graph.invoke(data(), config("a"))
        graph.invoke(data(), config("b"))
        assert graph.invoke(Command(resume=True), config("a"))["status"] == "created"
        assert graph.invoke(Command(resume=True), config("b"))["status"] == "recovered"
        assert store.count_tasks() == 1


def test_invalid_request_ends_without_interrupt(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        payload = {**data(), "due_at": "not-a-date"}
        output = graph.invoke(payload, config("invalid"))
        assert output["status"] == "invalid"
        assert "__interrupt__" not in output
        assert store.count_tasks() == 0


def test_different_threads_do_not_share_approval_state(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        graph.invoke(data(), config("first"))
        assert graph.get_state(config("second")).values == {}

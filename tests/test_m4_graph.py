"""Offline M4 LangGraph tests; requires installed project dependencies."""

from langgraph.graph import END

from productivity_agent.services.task_store import SQLiteTaskStore
from productivity_agent.workflows.reliable_task import build_reliable_task_graph

DUE = "2026-11-03T15:00:00+08:00"


def args(key="operation-m4-01", **kwargs):
    return {"operation_id": key, "title": "准备组会", "due_at": DUE, "max_attempts": 3, **kwargs}


def test_after_commit_timeout_is_reconciled(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    graph = build_reliable_task_graph(store, fault_plan={1: "after_commit"})
    output = graph.invoke(args())
    assert output["status"] == "recovered"
    assert output["attempts"] == 1
    assert store.count_tasks() == 1


def test_retry_before_commit_then_succeed(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    graph = build_reliable_task_graph(store, fault_plan={1: "before_commit"})
    output = graph.invoke(args())
    assert output["status"] == "created"
    assert output["attempts"] == 2
    assert store.count_tasks() == 1


def test_retry_budget_exhaustion(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    graph = build_reliable_task_graph(store, fault_plan={1: "before_commit", 2: "before_commit"})
    output = graph.invoke(args(max_attempts=2))
    assert output["status"] == "failed"
    assert output["attempts"] == 2
    assert store.count_tasks() == 0


def test_invalid_input_is_not_retried(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    graph = build_reliable_task_graph(store)
    output = graph.invoke(args(due_at="2026-11-03T15:00:00"))
    assert output["status"] == "failed"
    assert store.count_tasks() == 0


def test_rerunning_same_operation_after_restart_is_safe(tmp_path):
    db_path = tmp_path / "tasks.db"
    first = build_reliable_task_graph(SQLiteTaskStore(db_path)).invoke(args())
    second = build_reliable_task_graph(SQLiteTaskStore(db_path)).invoke(args())
    assert first["task"]["id"] == second["task"]["id"]
    assert second["status"] == "recovered"


def test_same_operation_id_different_payload_fails(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    graph = build_reliable_task_graph(store)
    assert graph.invoke(args())["status"] == "created"
    result = graph.invoke(args(title="另外一个任务"))
    assert result["status"] == "failed"
    assert store.count_tasks() == 1

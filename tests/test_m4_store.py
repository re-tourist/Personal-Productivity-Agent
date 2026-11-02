"""Offline M4 SQLite transaction tests. No LangGraph or paid API needed."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from productivity_agent.services.task_store import (
    AmbiguousCommitError,
    IdempotencyConflict,
    SQLiteTaskStore,
    TransientWriteError,
)

DUE = "2026-11-03T15:00:00+08:00"


def test_same_operation_creates_only_one_task(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    first = store.create_task("logical-op-1", "准备组会", DUE)
    again = store.create_task("logical-op-1", "准备组会", DUE)
    assert first["status"] == "created"
    assert again["status"] == "replayed"
    assert first["task"]["id"] == again["task"]["id"]
    assert store.count_tasks() == 1


def test_after_commit_timeout_does_not_duplicate(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    with pytest.raises(AmbiguousCommitError):
        store.create_task("logical-op-2", "准备组会", DUE, fault="after_commit")
    task = store.lookup("logical-op-2", "准备组会", DUE)
    assert task is not None
    assert store.create_task("logical-op-2", "准备组会", DUE)["task"]["id"] == task["id"]
    assert store.count_tasks() == 1


def test_before_commit_failure_does_not_create_task(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    with pytest.raises(TransientWriteError):
        store.create_task("logical-op-3", "准备组会", DUE, fault="before_commit")
    assert store.count_tasks() == 0
    assert store.lookup("logical-op-3", "准备组会", DUE) is None


def test_same_key_different_request_is_rejected(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    store.create_task("logical-op-4", "准备组会", DUE)
    with pytest.raises(IdempotencyConflict):
        store.create_task("logical-op-4", "召开组会", DUE)
    assert store.count_tasks() == 1


def test_sqlite_persists_across_store_instances(tmp_path):
    path = tmp_path / "tasks.db"
    a = SQLiteTaskStore(path)
    old = a.create_task("logical-op-5", "准备组会", DUE)
    b = SQLiteTaskStore(path)
    new = b.create_task("logical-op-5", "准备组会", DUE)
    assert old["task"]["id"] == new["task"]["id"]
    assert b.count_tasks() == 1


def test_same_instant_different_timezone_is_same_request(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    old = store.create_task("logical-op-6", "准备组会", DUE)
    new = store.create_task("logical-op-6", "准备组会", "2026-11-03T07:00:00+00:00")
    assert old["task"]["id"] == new["task"]["id"]
    assert store.count_tasks() == 1


def test_concurrent_duplicate_writes_are_serialized(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: store.create_task("logical-op-7", "准备组会", DUE), range(6)))
    assert len({r["task"]["id"] for r in results}) == 1
    assert store.count_tasks() == 1


def test_missing_timezone_is_rejected(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    with pytest.raises(ValueError, match="timezone"):
        store.create_task("logical-op-8", "准备组会", "2026-11-03T15:00:00")
    assert store.count_tasks() == 0

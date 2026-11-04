"""Synthetic real-SQLite policy oracle, runnable against immutable old source."""
import json
import sqlite3
import sys
import uuid
from pathlib import Path

from productivity_agent.services.task_store import (
    AmbiguousCommitError,
    SQLiteTaskStore,
)
from productivity_agent.workflows.reliable_task import build_reliable_task_graph

DUE = "2026-11-04T15:00:00+08:00"
CASES = ["created", "replayed", "conflict", "before_commit", "exhausted", "after_commit",
         "connection", "sqlite", "lookup_connection", "lookup_sqlite", "lookup_unavailable",
         "raw_timeout", "bad_time", "bad_limit", "boolean_limit", "blank_title"]


def observe(root, case, *, direct=False):
    calls = []

    class Store(SQLiteTaskStore):
        def create_task(self, *args, fault=None):
            calls.append("create")
            attempt = calls.count("create")
            if case == "connection" and attempt == 1:
                raise ConnectionError("synthetic connection")
            if case == "sqlite" and attempt == 1:
                raise sqlite3.OperationalError("synthetic sqlite")
            if case == "raw_timeout":
                raise TimeoutError("unclassified timeout")
            if case.startswith("lookup_"):
                if attempt == 1:
                    super().create_task(*args)
                raise AmbiguousCommitError("uncertain committed write")
            if case == "before_commit" and attempt == 1 or case == "exhausted":
                fault = "before_commit"
            elif case == "after_commit" and attempt == 1:
                fault = "after_commit"
            return super().create_task(*args, fault=fault)

        def lookup(self, *args):
            calls.append("lookup")
            if case == "lookup_connection":
                raise ConnectionError("read unavailable")
            if case == "lookup_sqlite":
                raise sqlite3.OperationalError("read unavailable")
            if case == "lookup_unavailable":
                raise RuntimeError("business_read_unavailable")
            return super().lookup(*args)

    # IDs and data are deterministic; each case has a separate fresh business DB.
    original_uuid = uuid.uuid4
    uuid.uuid4 = lambda: uuid.UUID("77777777-7777-4777-8777-777777777777")
    try:
        store = Store(root / (case + ".sqlite"))
        if case in {"replayed", "conflict"}:
            SQLiteTaskStore.create_task(store, "op", "other" if case == "conflict" else "task", DUE)
        args = {"operation_id": "op", "title": "task", "due_at": DUE, "max_attempts": 2}
        if case == "bad_time":
            args["due_at"] = "invalid"
        if case == "bad_limit":
            args["max_attempts"] = 6
        if case == "boolean_limit":
            args["max_attempts"] = True  # Preserve legacy isinstance(bool, int).
        if case == "blank_title":
            args["title"] = " "
        try:
            if direct:
                from productivity_agent.application.use_cases.task_creation import (
                    create_task_reliably,
                )
                result = create_task_reliably(store, approved=True, **args)
            else:
                result = build_reliable_task_graph(store).invoke(args)
            outcome = {"result": result}
        except Exception as exc:  # noqa: BLE001 -- characterize exact legacy exception behavior.
            outcome = {"exception": type(exc).__name__, "message": str(exc)}
        return {**outcome, "calls": calls, "tasks": store.list_tasks()}
    finally:
        uuid.uuid4 = original_uuid


if __name__ == "__main__":
    root = Path(sys.argv[1])
    root.mkdir()
    result = {case: observe(root, case) for case in CASES}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

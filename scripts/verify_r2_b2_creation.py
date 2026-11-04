"""Fixed-old intermediate creation checkpoints -> B2 -> fresh terminal verifier.

Both direct Approval and trusted Tool-nested drivers are interrupted inside real
SQLite-backed execution. Never calls a model or writes user data.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TypedDict

REPO = Path(__file__).resolve().parents[1]


class LostExecution(BaseException):
    """Synthetic node interruption; deliberately not caught by production."""


class OuterState(TypedDict):
    operation_id: str
    title: str
    due_at: str
    outcome: dict


def run_worker(root, phase, case):
    started_ns = time.time_ns()
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.config import get_config
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    import productivity_agent
    from productivity_agent.services.task_store import SQLiteTaskStore
    from productivity_agent.tools.reliable_task import build_safe_create_task_tool
    from productivity_agent.workflows.approval_session import build_approval_graph

    calls = []
    is_retry = case.endswith("retry")

    def record(method):
        config = get_config()
        cfg = config["configurable"]
        calls.append({"method": method, "thread_id": cfg["thread_id"],
                      "namespace": cfg["checkpoint_ns"],
                      "saver": type(cfg.get("__pregel_checkpointer")).__name__,
                      "recursion_limit": config["recursion_limit"]})

    class Store(SQLiteTaskStore):
        def create_task(self, *args, fault=None):
            record("create")
            if phase == "produce":
                if is_retry and sum(c["method"] == "create" for c in calls) == 2:
                    raise LostExecution("lost before second attempt")
                fault = "before_commit" if is_retry else "after_commit"
            return super().create_task(*args, fault=fault)

        def lookup(self, *args):
            record("lookup")
            if phase == "produce":
                raise LostExecution("lost in reconciliation")
            return super().lookup(*args)

    store = Store(root / "tasks.sqlite")
    cfg = {"configurable": {"thread_id": "historical-" + case}, "recursion_limit": 27}
    manifest = root / "manifest.json"
    with SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")) as saver:
        if case.startswith("approval"):
            graph = build_approval_graph(store, saver)
        else:
            def execute(state):
                tool = build_safe_create_task_tool(store, state["operation_id"])
                return {"outcome": tool.invoke({"title": state["title"], "due_at": state["due_at"]})}

            builder = StateGraph(OuterState)
            builder.add_node("execute", execute)
            builder.add_edge(START, "execute")
            builder.add_edge("execute", END)
            graph = builder.compile(checkpointer=saver)

        def snapshot():
            snap = graph.get_state(cfg)
            latest = {}
            for row in saver.list(None):
                ns = row.config["configurable"].get("checkpoint_ns", "")
                if ns and ns not in latest:
                    values = row.checkpoint["channel_values"]
                    latest[ns] = {k: values[k] for k in ["operation_id", "status", "attempts", "last_error_type"]
                                  if k in values}
            return {"next": list(snap.next), "values": snap.values, "children": latest}

        before = snapshot()
        if phase == "produce":
            args = {"operation_id": "stable-creation", "title": "synthetic approval",
                    "due_at": "2026-11-04T15:00:00+08:00"}
            if case.startswith("approval"):
                pending = graph.invoke(args, cfg)
                assert "__interrupt__" in pending and store.count_tasks() == 0
                args = Command(resume=True)
            try:
                graph.invoke(args, cfg)
            except LostExecution:
                pass
            else:
                raise AssertionError("intermediate loss injection did not run")
            after = snapshot()
            assert after["next"] == ["execute"]
            assert len(after["children"]) == 1
            child = next(iter(after["children"].values()))
            assert child["attempts"] == 1
            assert child["status"] == ("retrying" if is_retry else "ambiguous")
            manifest.write_text(json.dumps({"snapshot": after, "calls": calls}), encoding="utf-8")
        else:
            produced = json.loads(manifest.read_text(encoding="utf-8"))
            if phase == "consume":
                assert before == produced["snapshot"], "old execution state changed before resuming"
            graph.invoke(None, cfg)
            after = snapshot()
            assert after["next"] == []
            outcome = after["values"].get("outcome", after["values"])
            assert outcome["status"] == ("created" if is_retry else "recovered")
            if phase == "consume":
                assert len(calls) == 1, "completed child steps were unexpectedly repeated"
                assert calls[0] == produced["calls"][-1], "nested execution identity/config changed"
                assert set(after["children"]) == set(produced["snapshot"]["children"])
            else:
                assert not calls, "terminal replay entered the business capability"
            child = next(iter(after["children"].values()))
            assert child["operation_id"] == "stable-creation"
            assert child["attempts"] == (2 if is_retry else 1)
            assert child["status"] == outcome["status"]
        assert store.count_tasks() == (0 if phase == "produce" and is_retry else 1)
        with sqlite3.connect(store.db_path) as conn:
            count = conn.execute("SELECT count(*) FROM task_operations").fetchone()[0]
        tasks = store.list_tasks()
        assert count == len(tasks)
        if tasks:
            assert tasks[0]["version"] == 1
            if phase != "produce":
                assert outcome["task"] == tasks[0]
        for call in calls:
            assert call["saver"] == "SqliteSaver" and call["recursion_limit"] == 27
    return {"pid": os.getpid(), "started_ns": started_ns,
            "phase": phase, "source": str(Path(productivity_agent.__file__).parent),
            "calls": calls, "snapshot": after, "tasks": tasks, "operation_count": count}


def verify(root):
    from scripts.verify_r2_baseline import BASELINE, environment, export_baseline, source_manifest

    root.mkdir(parents=True, exist_ok=True)
    old = export_baseline(root / "baseline")
    current = REPO / "src"
    report = {"baseline": BASELINE, "baseline_source": source_manifest(old),
              "candidate_source": source_manifest(current), "cases": {}, "live_model_calls": 0}
    for case in ["approval-reconcile", "approval-retry", "tool-reconcile", "tool-retry"]:
        folder = root / case
        folder.mkdir()
        phases = {}
        for phase, source in [("produce", old), ("consume", current), ("verify", current)]:
            with (folder / (phase + ".log")).open("w", encoding="utf-8") as log:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker",
                                         case, phase, str(folder)], cwd=root, env=environment(source),
                                        stdout=log, stderr=log, timeout=60, check=False)
            assert result.returncode == 0, f"{case}/{phase}: inspect {folder / (phase + '.log')}"
            data = json.loads((folder / (phase + ".json")).read_text(encoding="utf-8"))
            assert Path(data["source"]) == source / "productivity_agent"
            phases[phase] = data
        # Sequentially terminated Windows processes can reuse a PID. Include the
        # worker's entry time; subprocess.run above starts each fresh interpreter.
        assert len({(p["pid"], p["started_ns"]) for p in phases.values()}) == 3
        assert phases["consume"]["tasks"] == phases["verify"]["tasks"]
        if phases["produce"]["tasks"]:
            assert phases["produce"]["tasks"] == phases["consume"]["tasks"]
        assert phases["consume"]["operation_count"] == phases["verify"]["operation_count"] == 1
        report["cases"][case] = phases
    return report


def main():
    if sys.argv[1:2] == ["--worker"]:
        case, phase, folder = sys.argv[2:]
        root = Path(folder)
        data = run_worker(root, phase, case)
        (root / (phase + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cache = REPO / ".pytest_cache/r2-b2"
    cache.mkdir(parents=True, exist_ok=True)
    report = verify(Path(tempfile.mkdtemp(prefix="run-", dir=cache)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "cases": list(report["cases"]), "live_model_calls": 0}))


if __name__ == "__main__":
    main()

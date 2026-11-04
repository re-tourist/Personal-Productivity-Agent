"""Fixed-old-source nested calendar recovery, including the removed Tool hop.

Assistant uses its real HTTP factory/AsyncSqliteSaver; M2/M3 use an outer graph
and SqliteSaver to expose their inherited nested persistence. No paid models.
"""
import argparse
import importlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

REPO = Path(__file__).resolve().parents[1]


class LostRead(BaseException):
    """Test-only process-loss boundary; do not let `except Exception` finish it."""


class OuterState(TypedDict):
    input: dict
    outcome: dict


def encode(value):
    return value.model_dump(mode="json")


def run_worker(root, phase, case):
    import hashlib

    from fastapi.testclient import TestClient
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.config import get_config
    from langgraph.graph import END, START, StateGraph

    import productivity_agent
    from productivity_agent.api.app import create_app
    from productivity_agent.bootstrap import bind_user_resources
    from productivity_agent.domain.agent_intent import AgentIntent
    from productivity_agent.domain.intent import ScheduleIntent
    from productivity_agent.tools.productivity import MockProductivityBackend
    from productivity_agent.workflows.calendar import build_graph
    from productivity_agent.workflows.natural_language import build_natural_language_graph
    from productivity_agent.workflows.tool_agent import build_tool_agent

    now, at, end = "2026-11-03T12:00:00+08:00", "2026-11-04T00:00:00+08:00", "2026-11-04T00:30:00+08:00"
    backend = MockProductivityBackend(events=[{
        "title": "overnight", "start_at": "2026-11-03T23:30:00+08:00", "end_at": "2026-11-04T01:00:00+08:00"}])
    busy = [{"start_at": e["start_at"], "end_at": e["end_at"]} for e in backend.events]

    class Extractor:
        def invoke(self, messages):
            if case.startswith("assistant"):
                return AgentIntent(action="check_calendar", title="cross-midnight", at=at, duration_minutes=30)
            return ScheduleIntent(action="schedule_event", title="cross-midnight", start_at=at,
                                  duration_minutes=30, clarification_question=None)

    class Model:
        def bind_tools(self, tools):
            assert "create_task" not in {t.name for t in tools}
            return self

        def invoke(self, messages):
            if any(isinstance(m, ToolMessage) for m in messages):
                return AIMessage(content="observed calendar", id="b1-final")
            return AIMessage(content="", id="b1-tool-request", tool_calls=[{
                "name": "check_calendar_conflict", "args": {"title": "cross-midnight", "start_at": at, "end_at": end},
                "id": "b1-calendar-call", "type": "tool_call"}])

    # Select by the implementation function, not the legacy facade's globals.
    module = importlib.import_module(build_graph.__module__)
    original = module.has_conflict
    calls = []

    def probe(*args):
        cfg = get_config()["configurable"]
        calls.append({"thread_id": cfg["thread_id"], "namespace": cfg["checkpoint_ns"],
                      "saver": type(cfg.get("__pregel_checkpointer")).__name__})
        if phase == "produce":
            raise LostRead("synthetic interruption inside historical Calendar child")
        return original(*args)

    module.has_conflict = probe
    manifest = root / "manifest.json"
    if case.startswith("assistant"):
        os.environ["PPA_DATA_DIR"] = str(root)
        authenticated = case == "assistant-auth"
        headers = {}
        if authenticated:
            credential = root / "credential"
            if not credential.exists():
                credential.write_text(secrets.token_hex(24), encoding="utf-8")
            token = credential.read_text(encoding="utf-8")
            auth = root / "accounts.auth.json"
            auth.write_text(json.dumps({"users": {
                "b1-owner": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()},
                "b1-other": {"token_sha256": hashlib.sha256((token + "x").encode()).hexdigest()}}}), encoding="utf-8")
            os.environ["PPA_AUTH_CONFIG"] = str(auth)
            headers = {"Authorization": "Bearer " + token}
        app = create_app(api_token="", session_extractor=Extractor(), session_backend=backend)
        with TestClient(app) as api:
            if phase == "produce":
                tid = api.post("/v1/assistant/sessions", headers=headers).json()["thread_id"]
                resources = bind_user_resources(app.state, "b1-owner", token) if authenticated else app.state
                key = f"assistant:b1-owner:{tid}" if authenticated else f"assistant:{tid}"

                async def interrupt_read():
                    try:
                        await resources.assistant_graph.ainvoke({"initialize": False, "history": [],
                            "user_text": "明天凌晨检查日程", "reference_now": now, "timezone": "Asia/Shanghai"},
                            {"configurable": {"thread_id": key}, "recursion_limit": 20})
                    except LostRead:
                        return
                    raise AssertionError("read interruption did not execute")

                api.portal.call(interrupt_read)
                view = api.get(f"/v1/assistant/sessions/{tid}", headers=headers).json()
                assert view["status"] == "interrupted"
                manifest.write_text(json.dumps({"thread_id": tid, "before": view}), encoding="utf-8")
            else:
                prior = json.loads(manifest.read_text(encoding="utf-8"))
                tid = prior["thread_id"]
                path = f"/v1/assistant/sessions/{tid}"
                before = api.get(path, headers=headers).json()
                assert before == prior["before" if phase == "consume" else "final"]
                if authenticated:
                    assert api.get(path).status_code == 401
                    assert api.get(path, headers={"Authorization": "Bearer " + token + "x"}).status_code == 404
                response = api.post(path + "/recover", headers=headers)
                assert response.status_code == 200
                view = response.json()
                assert view["status"] == "completed" and view["result"]["events"] == []
                assert view["result"]["calendar"]["suggested_start"] == "2026-11-04T01:00:00+08:00"
                assert view["approval"] is None
                if phase == "consume":
                    manifest.write_text(json.dumps({**prior, "final": view}), encoding="utf-8")
                else:
                    assert view == prior["final"]
            assert api.get("/v1/tasks", headers=headers).json()["items"] == []
        db = root / "m6-checkpoints.sqlite"
        with sqlite3.connect(root / "tasks.sqlite") as conn:
            assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        outcome = view
    else:
        if case == "natural":
            inner = build_natural_language_graph(Extractor())
            payload = {"user_text": "明天凌晨检查日程", "reference_now": now, "busy_slots": busy}
        else:
            inner = build_tool_agent(Model(), backend)
            payload = {"messages": [HumanMessage(content="check calendar", id="b1-user")],
                       "reference_now": now, "llm_calls": 0}
        db = root / "nested.sqlite"
        with SqliteSaver.from_conn_string(str(db)) as saver:
            builder = StateGraph(OuterState)
            builder.add_node("run", lambda state: {"outcome": inner.invoke(state["input"])})
            builder.add_edge(START, "run")
            builder.add_edge("run", END)
            graph = builder.compile(checkpointer=saver)
            config = {"configurable": {"thread_id": "b1-" + case}}
            if phase == "produce":
                try:
                    graph.invoke({"input": payload}, config)
                except LostRead:
                    pass
                else:
                    raise AssertionError("nested interruption did not execute")
                assert graph.get_state(config).next == ("run",)
                outcome = {"next": ["run"]}
            else:
                if phase == "consume":
                    graph.invoke(None, config)
                snapshot = graph.get_state(config)
                assert snapshot.next == ()
                result = snapshot.values["outcome"]
                if case == "natural":
                    assert result["result"]["suggested_start"] == "2026-11-04T01:00:00+08:00"
                else:
                    assert result["messages"][-1].content == "observed calendar"
                    tool_result = next(m for m in result["messages"] if isinstance(m, ToolMessage))
                    assert json.loads(tool_result.content)["suggested_start"] == "2026-11-04T01:00:00+08:00"
                outcome = json.loads(json.dumps(result, default=encode))
                if phase == "consume":
                    manifest.write_text(json.dumps(outcome), encoding="utf-8")
                else:
                    assert outcome == json.loads(manifest.read_text(encoding="utf-8"))
            assert backend.tasks == []
    with sqlite3.connect(db) as conn:
        namespaces = [r[0] for r in conn.execute("SELECT DISTINCT checkpoint_ns FROM checkpoints ORDER BY checkpoint_ns")]
    assert any(namespaces)
    assert len(calls) == (0 if phase == "verify" else 1)
    return {"source_root": str(Path(productivity_agent.__file__).resolve().parent), "pid": os.getpid(),
            "calls": calls, "namespaces": namespaces, "outcome": outcome, "business_writes": 0}


def verify(root):
    from scripts.verify_r2_baseline import BASELINE, environment, export_baseline

    root.mkdir(parents=True, exist_ok=True)
    old = export_baseline(root / "baseline")
    report = {"baseline": BASELINE, "live_model_calls": 0, "cases": {}}
    for case in ["assistant-legacy", "assistant-auth", "natural", "tool"]:
        folder = root / case
        folder.mkdir()
        phases = {}
        for phase, source in [("produce", old), ("consume", REPO / "src"), ("verify", REPO / "src")]:
            env = environment(source)
            env["PYTHONPATH"] = os.pathsep.join([str(source), str(REPO)])
            with (folder / f"{phase}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker",
                    "--root", str(folder), "--phase", phase, "--case", case],
                    cwd=folder, env=env, stdout=log, stderr=log, check=False, timeout=120)
            assert result.returncode == 0, f"inspect {folder / f'{phase}.log'}"
            data = json.loads((folder / f"{phase}.json").read_text(encoding="utf-8"))
            assert Path(data["source_root"]) == source / "productivity_agent"
            phases[phase] = data
        assert set(phases["produce"]["namespaces"]) <= set(phases["consume"]["namespaces"])
        assert phases["produce"]["calls"][0]["namespace"] == phases["consume"]["calls"][0]["namespace"]
        assert phases["produce"]["calls"][0]["saver"] == phases["consume"]["calls"][0]["saver"]
        report["cases"][case] = phases
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("reports/r2-b1/nested-read-compatibility.json"))
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--phase")
    parser.add_argument("--case")
    args = parser.parse_args()
    if args.worker:
        assert os.getenv("PPA_ENABLE_LIVE_QWEN") == "0" and not os.getenv("DASHSCOPE_API_KEY")
        result = run_worker(args.root, args.phase, args.case)
        (args.root / f"{args.phase}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        cache = REPO / ".pytest_cache/r2-b1-reads"
        cache.mkdir(parents=True, exist_ok=True)
        result = verify(Path(tempfile.mkdtemp(prefix="run-", dir=cache)))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "cases": list(result["cases"]), "live_model_calls": 0}))


if __name__ == "__main__":
    main()

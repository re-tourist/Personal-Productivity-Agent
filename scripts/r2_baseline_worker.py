"""B0 test-only worker. PYTHONPATH selects the immutable producer or candidate source.

All input is synthetic. No model SDK is constructed. Runtime instrumentation calls
the original store first; a BaseException simulates losing a process after commit.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import inspect
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.config import get_config
from langgraph.types import Command

import productivity_agent
from productivity_agent.api.app import create_app
from productivity_agent.api.task_service import create_task_service
from productivity_agent.bootstrap import bind_user_resources
from productivity_agent.domain.agent_intent import AgentIntent
from productivity_agent.domain.intent import ScheduleIntent
from productivity_agent.infrastructure.integrations.http_task_store import HTTPTaskStore
from productivity_agent.infrastructure.models.offline_intent import OfflineIntentExtractor
from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
from productivity_agent.tools.productivity import MockProductivityBackend, build_productivity_tools
from productivity_agent.tools.reliable_task import build_safe_create_task_tool
from productivity_agent.workflows.approval_session import build_approval_graph
from productivity_agent.workflows.assistant import build_assistant_graph
from productivity_agent.workflows.calendar import build_graph
from productivity_agent.workflows.chat_memory import build_chat_memory_graph
from productivity_agent.workflows.natural_language import build_natural_language_graph
from productivity_agent.workflows.reliable_task import build_reliable_task_graph
from productivity_agent.workflows.tool_agent import build_tool_agent

BASELINE = "40d837c19f42ffd373686c30f4797df2e2598e23"
NOW = "2026-11-03T12:00:00+08:00"
DUE = "2026-11-04T15:00:00+08:00"
ROOT = Path(productivity_agent.__file__).resolve().parent


class ScriptedModel:
    """Only the model boundary is scripted; the graph and ToolNode remain real."""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="offline tool result")
        return AIMessage(content="", tool_calls=[{
            "name": "list_tasks", "args": {}, "id": "b0-call", "type": "tool_call",
        }])


class InjectedCallbackFailure(BaseCallbackHandler):
    """Deterministic exception at a real graph boundary, without a fake graph."""
    raise_error = True

    def on_chain_start(self, serialized, inputs, **kwargs):
        raise RuntimeError("synthetic internal error must not escape the HTTP boundary")


def routes(router):
    result = []
    for route in router.routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            result.extend(routes(included))
        elif hasattr(route, "methods"):
            result.append({"path": route.path, "methods": sorted(route.methods),
                           "name": route.name, "operation_id": getattr(route, "operation_id", None)
                           or getattr(route, "unique_id", None)})
    return result


def stable(value):
    """Normalize only generated UUIDs, preserving references and message bytes otherwise."""
    import re
    mapping = {}

    def replace(match):
        key = match.group(0)
        return mapping.setdefault(key, f"<uuid-{len(mapping) + 1}>")

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return json.loads(re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                             replace, encoded))


def observe(response):
    result = {"status": response.status_code,
              "headers": {k: v for k, v in response.headers.items()
                          if k in {"content-type", "cache-control", "x-accel-buffering", "location"}}}
    if response.headers.get("content-type", "").startswith("application/json"):
        result["json"] = response.json()
    else:
        result["text"] = response.text
    return result


def graph_contract(graph):
    drawable = graph.get_graph()
    channels = {}
    for name, channel in graph.channels.items():
        if name.startswith(("__", "branch:")):
            continue
        operator = getattr(channel, "operator", None)
        channels[name] = {"channel": type(channel).__name__,
                          "reducer": (operator.__module__ + "." + operator.__qualname__)
                          if operator else None}
    def type_contract(annotation):
        origin = get_origin(annotation)
        if origin:
            return {"origin": str(origin), "args": [type_contract(a) for a in get_args(annotation)]}
        if hasattr(annotation, "__qualname__"):
            return annotation.__module__ + "." + annotation.__qualname__
        # Pydantic's discriminator repr embeds an ASLR function address; its
        # function name and all semantic FieldInfo data are retained.
        return re.sub(r" at 0x[0-9a-fA-F]+", "", repr(annotation))

    schema = graph.builder.state_schema
    return {"nodes": list(drawable.nodes),
            "edges": sorted([{"source": e.source, "target": e.target, "conditional": e.conditional}
                             for e in drawable.edges], key=lambda x: (x["source"], x["target"])),
            "channels": channels, "input_schema": graph.get_input_jsonschema(),
            "state_fields": {k: type_contract(v) for k, v in get_type_hints(schema, include_extras=True).items()},
            "required_keys": sorted(schema.__required_keys__), "optional_keys": sorted(schema.__optional_keys__),
            "output_schema": graph.get_output_jsonschema(),
            "checkpointer": type(graph.checkpointer).__name__,
            "interrupt_before": graph.interrupt_before_nodes,
            "interrupt_after": graph.interrupt_after_nodes}


def contracts(root):
    backend = MockProductivityBackend(events=[{
        "title": "overnight", "start_at": "2026-11-02T23:30:00+08:00",
        "end_at": "2026-11-03T01:00:00+08:00",
    }])
    store = SQLiteTaskStore(root / "contracts.sqlite")
    toolset = build_productivity_tools(backend, allow_mock_writes=True)
    safe = build_safe_create_task_tool(store, "b0-tool")
    tools = {t.name: {"description": t.description, "args": t.args_schema.model_json_schema()}
             for t in toolset}
    tools["trusted_create_task"] = {"name": safe.name, "description": safe.description,
                                    "args": safe.args_schema.model_json_schema(),
                                    "return": safe.invoke({"title": "tool fixture", "due_at": DUE})}
    tools["outputs"] = {t.name: t.invoke(args) for t, args in zip(toolset, [
        {"date_iso": "2026-11-03"},
        {"title": "new", "start_at": "2026-11-03T00:00:00+08:00",
         "end_at": "2026-11-03T00:30:00+08:00"}, {},
        {"title": "mock", "due_at": DUE},
    ], strict=True)}
    prompts = {}
    for name in ["assistant", "natural_language", "tool_agent"]:
        tree = ast.parse((ROOT / "workflows" / (name + ".py")).read_text(encoding="utf-8"))
        # Freeze every multiline literal, including the complete inline system prompts.
        prompts[name] = [n.value for n in ast.walk(tree)
                         if isinstance(n, ast.Constant) and isinstance(n.value, str) and "\n" in n.value]
    with SqliteSaver.from_conn_string(str(root / "graph-contracts.sqlite")) as saver:
        graphs = {
            "assistant": build_assistant_graph(OfflineIntentExtractor(), store, saver, backend),
            "approval": build_approval_graph(store, saver), "reliable": build_reliable_task_graph(store),
            "calendar": build_graph(), "natural_language": build_natural_language_graph(OfflineIntentExtractor()),
            "tool_agent": build_tool_agent(ScriptedModel(), backend),
            "chat_memory": build_chat_memory_graph(saver),
        }
        graph_data = {k: graph_contract(v) for k, v in graphs.items()}
    app = create_app(api_token="", live_agent=build_tool_agent(ScriptedModel(), backend))
    with TestClient(app) as api:
        http = {"assistant_openapi": app.openapi(), "assistant_routes": routes(app.router)}
        http["responses"] = {
            "root": observe(api.get("/", follow_redirects=False)),
            "app_sha256_lf": hashlib.sha256(api.get("/app").content.replace(b"\r\n", b"\n")).hexdigest(),
            "identity": observe(api.get("/v1/me")),
            "calendar": observe(api.post("/v1/calendar/check", json={
                "request": {"title": "fixture", "start_at": DUE, "end_at": "2026-11-04T16:00:00+08:00"}})),
            "calendar_sse": observe(api.post("/v1/calendar/check/stream", json={
                "request": {"title": "fixture", "start_at": DUE, "end_at": "2026-11-04T16:00:00+08:00"}})),
            "agent": observe(api.post("/v1/agent/ask", json={"message": "tasks", "reference_now": NOW})),
            "agent_sse": observe(api.post("/v1/agent/stream", json={"message": "tasks", "reference_now": NOW})),
        }
        tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        message = {"message": "明天下午三点提醒我准备组会", "reference_now": NOW,
                   "timezone": "Asia/Shanghai", "message_id": "00000000-0000-4000-8000-000000000001"}
        http["responses"]["assistant_sse"] = observe(api.post(
            f"/v1/assistant/sessions/{tid}/messages/stream", json=message))
        http["responses"]["assistant_pending_error_sse"] = observe(api.post(
            f"/v1/assistant/sessions/{tid}/messages/stream", json={**message,
                "message_id": "00000000-0000-4000-8000-000000000002"}))
        draft = api.post("/v1/tasks/drafts", json={"title": "draft", "due_at": DUE})
        http["responses"]["draft"] = observe(draft)
        dtid = draft.json()["thread_id"]
        http["responses"]["draft_reject"] = observe(api.post(
            f"/v1/tasks/drafts/{dtid}/decision", json={"approved": False}))
        http["responses"]["draft_replay"] = observe(api.post(
            f"/v1/tasks/drafts/{dtid}/decision", json={"approved": False}))
        ready_tid = api.post("/v1/assistant/sessions").json()["thread_id"]
        # Exercise exception handling with the REAL graphs and a test-only callback.
        app.state.calendar_graph = app.state.calendar_graph.with_config(callbacks=[InjectedCallbackFailure()])
        app.state.live_agent = app.state.live_agent.with_config(callbacks=[InjectedCallbackFailure()])
        app.state.assistant_graph = app.state.assistant_graph.with_config(callbacks=[InjectedCallbackFailure()])
        http["responses"]["calendar_error_sse"] = observe(api.post("/v1/calendar/check/stream", json={
            "request": {"title": "fixture", "start_at": DUE, "end_at": "2026-11-04T16:00:00+08:00"}}))
        http["responses"]["agent_error_sse"] = observe(api.post("/v1/agent/stream", json={
            "message": "tasks", "reference_now": NOW}))
        # Replaying the original message does not execute; use the READY session.
        http["responses"]["assistant_error_sse"] = observe(api.post(
            f"/v1/assistant/sessions/{ready_tid}/messages/stream", json=message))
    business = create_task_service(SQLiteTaskStore(root / "business-contracts.sqlite"))
    with TestClient(business) as api:
        http.update(business_openapi=business.openapi(), business_routes=routes(business.router))
        http["responses"]["business_unapproved"] = observe(api.post("/tasks", json={
            "operation_id": "unapproved", "title": "forbidden", "due_at": DUE, "approved": False}))
    signatures = {cls.__name__: {name: str(inspect.signature(getattr(cls, name))) for name in (
        ["invoke"] if cls is OfflineIntentExtractor else
        ["create_task", "change_task", "get_task", "list_tasks", "get_operation", "lookup", "for_owner"])}
        for cls in [SQLiteTaskStore, HTTPTaskStore, OfflineIntentExtractor]}
    return stable({"http": http, "graphs": graph_data, "prompts": prompts, "signatures": signatures,
                   "llm_schemas": {"agent": AgentIntent.model_json_schema(), "schedule": ScheduleIntent.model_json_schema()},
                   "tools": tools})


class LostAfterCommit(BaseException):
    """Test-only crash boundary; production's `except Exception` must not swallow it."""


def instrument(records, crash):
    for cls in [SQLiteTaskStore, HTTPTaskStore]:
        for method in ["create_task", "change_task"]:
            original = getattr(cls, method)

            def wrapped(self, *args, _original=original, _method=method, **kwargs):
                try:
                    config = get_config()
                except RuntimeError:
                    config = {}
                cfg = config.get("configurable", {})
                records.append({"method": _method, "operation_id": args[0],
                                "thread_id": cfg.get("thread_id"),
                                "checkpoint_ns": cfg.get("checkpoint_ns"),
                                "inherited_checkpointer": type(cfg.get("__pregel_checkpointer")).__name__,
                                "checkpoint_map_keys": sorted(cfg.get("checkpoint_map", {})),
                                "recursion_limit": config.get("recursion_limit")})
                result = _original(self, *args, **kwargs)
                if crash[0]:
                    crash[0] = False
                    raise LostAfterCommit("synthetic loss after durable write")
                return result

            setattr(cls, method, wrapped)


def web(root, phase, authenticated):
    data = root / "web"
    data.mkdir(exist_ok=True)
    os.environ["PPA_DATA_DIR"] = str(data)
    records, crash = [], [False]
    instrument(records, crash)
    headers = {}
    if authenticated:
        # Generated, disposable credentials never appear in fixtures or output.
        token_file = root / "credential"
        if not token_file.exists():
            import secrets
            token_file.write_text(secrets.token_hex(24), encoding="utf-8")
        token = token_file.read_text(encoding="utf-8")
        config_file = root / "accounts.json"
        config_file.write_text(json.dumps({"users": {
            "b0-owner": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()},
            "b0-other": {"token_sha256": hashlib.sha256((token + "x").encode()).hexdigest()},
        }}), encoding="utf-8")
        os.environ["PPA_AUTH_CONFIG"] = str(config_file)
        headers = {"Authorization": "Bearer " + token}
    else:
        os.environ["PPA_AUTH_CONFIG"] = ""
    manifest_path = root / "web-manifest.json"
    app = create_app(api_token="")
    with TestClient(app) as api:
        def request(method, path, body=None, extra_headers=None):
            response = api.request(method, path, json=body, headers=headers if extra_headers is None else extra_headers)
            assert response.status_code in {200, 201}, (path, response.status_code, response.text)
            return response.json()

        def say(tid, text):
            import uuid
            return request("POST", f"/v1/assistant/sessions/{tid}/messages", {
                "message": text, "reference_now": NOW, "timezone": "Asia/Shanghai", "message_id": str(uuid.uuid4())})

        resources = bind_user_resources(app.state, "b0-owner", token) if authenticated else app.state

        def cfg(kind, tid):
            key = f"{kind}:b0-owner:{tid}" if authenticated else f"assistant:{tid}" if kind == "assistant" else tid
            return {"configurable": {"thread_id": key}, "recursion_limit": 20}

        def checkpoint(kind, tid):
            graph = resources.assistant_graph if kind == "assistant" else resources.approval_graph
            snap = api.portal.call(graph.aget_state, cfg(kind, tid))
            return {"next": list(snap.next), "status": snap.values.get("status"),
                    "operation_id": snap.values.get("operation_id"), "approved": snap.values.get("approved"),
                    "task": snap.values.get("task") or (snap.values.get("result") or {}).get("task"),
                    "interrupts": [i.value for t in snap.tasks for i in t.interrupts]}

        def decide(kind, tid, decision):
            body = {"approved": decision}
            if kind == "assistant":
                body["operation_id"] = checkpoint(kind, tid)["operation_id"]
            return request("POST", f"/v1/{'assistant/sessions' if kind == 'assistant' else 'tasks/drafts'}/{tid}/decision", body)

        if phase == "produce":
            manifest = []
            for kind in ["assistant", "draft"]:
                scenarios = ["pending", "reject", "reject_on_resume", "approved", "before_execute", "after_commit"]
                if kind == "assistant":
                    scenarios += ["ready", "clarification", "update_after_commit", "complete_after_commit"]
                for scenario in scenarios:
                    prefix = f"/v1/{'assistant/sessions' if kind == 'assistant' else 'tasks/drafts'}"
                    body = {} if kind == "assistant" else {"title": "draft-" + scenario, "due_at": DUE}
                    tid = request("POST", prefix, body)["thread_id"]
                    if kind == "assistant" and scenario != "ready":
                        result = say(tid, "帮我创建一个准备组会的任务" if scenario == "clarification"
                                     else "明天下午三点提醒我准备组会")
                        assert result["status"] == ("clarification_required" if scenario == "clarification" else "awaiting_approval")
                    if scenario in {"reject", "approved"}:
                        decide(kind, tid, scenario == "approved")
                    elif scenario in {"before_execute", "after_commit", "update_after_commit", "complete_after_commit"}:
                        graph = resources.assistant_graph if kind == "assistant" else resources.approval_graph
                        if scenario in {"update_after_commit", "complete_after_commit"}:
                            created = decide(kind, tid, True)["result"]["task"]
                            text = (f"把任务 {created['id']} 改到后天上午十点" if scenario.startswith("update")
                                    else f"完成任务 {created['id']}")
                            pending = say(tid, text)
                            assert pending["status"] == "awaiting_approval", pending
                        crash[0] = scenario.endswith("after_commit")
                        async def drive(graph=graph, kind=kind, tid=tid, scenario=scenario):
                            # Catch inside the event loop: BaseException must not tear
                            # down AnyIO's portal before the saver flushes its writes.
                            try:
                                await graph.ainvoke(Command(resume=True), cfg(kind, tid),
                                                    interrupt_before=["execute"] if scenario == "before_execute" else None)
                            except LostAfterCommit:
                                assert scenario.endswith("after_commit")
                                return
                            assert scenario == "before_execute", "crash injection did not run"

                        api.portal.call(drive)
                    manifest.append({"kind": kind, "scenario": scenario, "thread_id": tid,
                                     "before": checkpoint(kind, tid)})
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            outcomes = manifest
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            outcomes = []
            for item in manifest:
                kind, scenario, tid = item["kind"], item["scenario"], item["thread_id"]
                before = checkpoint(kind, tid)
                if phase == "consume":
                    assert before == item["before"], (scenario, before, item["before"])
                base = f"/v1/{'assistant/sessions' if kind == 'assistant' else 'tasks/drafts'}/{tid}"
                if authenticated:
                    assert api.get(base, headers={}).status_code == 401
                    assert api.get(base, headers={"Authorization": "Bearer " + token + "x"}).status_code == 404
                if phase == "consume" and scenario == "clarification":
                    say(tid, "明天下午三点")
                if phase == "consume" and scenario == "ready":
                    say(tid, "明天下午三点提醒我准备组会")
                if phase == "consume" and scenario in {"pending", "clarification", "ready"}:
                    decide(kind, tid, True)
                elif phase == "consume" and scenario == "reject_on_resume":
                    decide(kind, tid, False)
                elif phase == "consume" and scenario == "before_execute":
                    if kind == "assistant":
                        request("POST", base + "/recover")
                    else:
                        # Draft has no recover endpoint; use its existing graph API.
                        api.portal.call(resources.approval_graph.ainvoke, None, cfg(kind, tid))
                elif phase == "consume" and scenario.endswith("after_commit"):
                    if kind == "assistant":
                        request("POST", base + "/recover")
                    else:
                        api.portal.call(resources.approval_graph.ainvoke, None, cfg(kind, tid))
                after = checkpoint(kind, tid)
                assert after["next"] == [], (scenario, after)
                expected = {"cancelled"} if scenario.startswith("reject") else {"created", "recovered", "updated", "completed"}
                assert after["status"] in expected, (scenario, after)
                if item["before"]["operation_id"]:
                    assert after["operation_id"] == item["before"]["operation_id"]
                task = after["task"]
                if task:
                    expected_version = 2 if scenario.startswith(("update_", "complete_")) else 1
                    assert task["version"] == expected_version, (scenario, task)
                    if item["before"]["task"]:
                        assert task["id"] == item["before"]["task"]["id"]
                replay = api.post(base + "/decision", json={"approved": not scenario.startswith("reject"),
                    **({"operation_id": after["operation_id"]} if kind == "assistant" else {})}, headers=headers)
                assert replay.status_code == (200 if kind == "assistant" else 409), replay.text
                outcomes.append({**item, "after": after, "decision_replay_status": replay.status_code})
        tasks = resources.store.list_tasks(limit=1000)
        assert len(tasks) == (6 if phase == "produce" else 12), (phase, tasks)
        if authenticated:
            other = {"Authorization": "Bearer " + token + "x"}
            assert request("GET", "/v1/tasks", extra_headers=other)["items"] == []
            assert api.get(f"/v1/tasks/{tasks[0]['id']}", headers=other).status_code == 404
        # Inspect the real saver, including function-invoked child graphs that
        # are not necessarily discoverable through get_graph(xray=True).
        async def child_checkpoints():
            latest = {}
            async for row in app.state.saver.alist(None):
                conf = row.config["configurable"]
                ns = conf.get("checkpoint_ns", "")
                key = (conf["thread_id"], ns)
                if ns and key not in latest:
                    latest[key] = {"thread_id": key[0], "namespace": ns,
                                   "format_version": row.checkpoint["v"],
                                   "values": {k: v for k, v in row.checkpoint["channel_values"].items()
                                              if not k.startswith(("__", "branch:"))},
                                   "pending_channels": [w[1] for w in row.pending_writes or []]}
            return list(latest.values())

        children = api.portal.call(child_checkpoints)
    checkpoint_db = data / "m6-checkpoints.sqlite"
    with sqlite3.connect(checkpoint_db) as conn:
        namespaces = [list(row) for row in conn.execute(
            "SELECT checkpoint_ns, count(*) FROM checkpoints GROUP BY checkpoint_ns ORDER BY checkpoint_ns")]
    return {"outcomes": outcomes, "calls": records, "tasks": tasks, "child_checkpoints": children,
            "namespaces": namespaces, "authenticated": authenticated,
            "remote": bool(os.getenv("PPA_TASK_SERVICE_URL"))}


def sync_graphs(root, phase):
    store = SQLiteTaskStore(root / "m5-tasks.sqlite")
    records, crash = [], [False]
    instrument(records, crash)
    outcomes = []
    with SqliteSaver.from_conn_string(str(root / "m5-checkpoints.sqlite")) as saver:
        graph = build_approval_graph(store, saver)
        for scenario in ["pending", "reject", "reject_on_resume", "approved", "before_execute", "after_commit"]:
            cfg = {"configurable": {"thread_id": "m5-" + scenario}, "recursion_limit": 23}
            if phase == "produce":
                graph.invoke({"operation_id": "op-" + scenario, "title": scenario, "due_at": DUE}, cfg)
                if scenario in {"reject", "approved"}:
                    graph.invoke(Command(resume=scenario == "approved"), cfg)
                elif scenario in {"before_execute", "after_commit"}:
                    crash[0] = scenario == "after_commit"
                    try:
                        graph.invoke(Command(resume=True), cfg,
                                     interrupt_before=["execute"] if scenario == "before_execute" else None)
                    except LostAfterCommit:
                        assert scenario == "after_commit"
            elif phase == "consume":
                if scenario == "pending":
                    graph.invoke(Command(resume=True), cfg)
                elif scenario == "reject_on_resume":
                    graph.invoke(Command(resume=False), cfg)
                elif scenario in {"before_execute", "after_commit"}:
                    graph.invoke(None, cfg)
            snap = graph.get_state(cfg)
            if phase != "produce":
                assert not snap.next
                expected = {"cancelled"} if scenario.startswith("reject") else {"created", "recovered"}
                assert snap.values["status"] in expected
            outcomes.append({"scenario": scenario, "next": list(snap.next), "values": snap.values,
                             "interrupts": [i.value for t in snap.tasks for i in t.interrupts]})
        namespaces = [list(row) for row in saver.conn.execute(
            "SELECT checkpoint_ns, count(*) FROM checkpoints GROUP BY checkpoint_ns ORDER BY checkpoint_ns")]
    with SqliteSaver.from_conn_string(str(root / "m5-chat-checkpoints.sqlite")) as saver:
        chat = build_chat_memory_graph(saver)
        cfg = {"configurable": {"thread_id": "m5-chat"}}
        before = chat.get_state(cfg)
        if phase == "produce":
            chat.invoke({"messages": [HumanMessage(content="baseline first", id="b0-human-1")]}, cfg)
            chat.invoke({"messages": [HumanMessage(content="baseline pending", id="b0-human-2")]}, cfg,
                        interrupt_before=["echo"])
        elif phase == "consume":
            assert before.next == ("echo",)
            result = chat.invoke(None, cfg)
            assert len(result["messages"]) == 4
            # add_messages must replace the old ID rather than append a duplicate.
            result = chat.invoke({"messages": [HumanMessage(content="edited", id="b0-human-1")]}, cfg)
            assert len(result["messages"]) == 5
            assert result["messages"][0].content == "edited"
        snap = chat.get_state(cfg)
        if phase == "verify":
            assert not snap.next and len(snap.values["messages"]) == 5
        chat_state = {"next": list(snap.next), "messages": [m.model_dump(mode="json") for m in snap.values["messages"]]}
    assert store.count_tasks() == (2 if phase == "produce" else 4)
    return {"approval": outcomes, "chat": chat_state, "calls": records, "namespaces": namespaces,
            "task_count": store.count_tasks(), "auth_scope": "M5 CLI is legacy-only; web matrix tests authenticated ownership"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["contracts", "web", "sync"])
    parser.add_argument("phase", choices=["produce", "consume", "verify"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--auth", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    assert os.getenv("PPA_ENABLE_LIVE_QWEN") == "0"
    assert not os.getenv("DASHSCOPE_API_KEY")
    if args.mode == "contracts":
        result = contracts(args.root)
    elif args.mode == "web":
        result = web(args.root, args.phase, args.auth)
    else:
        result = sync_graphs(args.root, args.phase)
    output = {"source_root": str(ROOT), "pid": os.getpid(), "phase": args.phase,
              "versions": {n: importlib.metadata.version(n) for n in [
                  "langgraph", "langgraph-checkpoint", "langgraph-checkpoint-sqlite", "langchain-core",
                  "langgraph-prebuilt", "aiosqlite", "ormsgpack", "fastapi", "starlette", "pydantic", "httpx"]}, "result": result}
    (args.root / f"{args.mode}-{args.phase}.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

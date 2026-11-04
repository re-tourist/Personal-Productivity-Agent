"""Independent use-case callers, fixed-old-calendar oracle, and data-source boundaries."""
import ast
import hashlib
import importlib
import json
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from test_task07_security import server

from productivity_agent.application.agent.tools.productivity import build_productivity_tools
from productivity_agent.application.agent.workflows.calendar import build_graph
from productivity_agent.application.use_cases import calendar, tasks
from productivity_agent.domain.calendar_rules import assess_calendar
from productivity_agent.infrastructure.integrations.http_task_store import (
    BusinessUnavailable,
    HTTPTaskStore,
)
from productivity_agent.infrastructure.integrations.mock_productivity import MockProductivityBackend
from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
from scripts.verify_r2_b1_reads import verify
from scripts.verify_r2_baseline import environment, export_baseline

pytest_plugins = ["test_task06_operations"]
REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src/productivity_agent"
DUE = "2026-11-04T15:00:00+08:00"
REQUEST = {"title": "meeting", "start_at": DUE, "end_at": "2026-11-04T16:00:00+08:00"}
CASES = [
    {"request": REQUEST, "busy_slots": []},
    {"request": REQUEST, "busy_slots": [{"start_at": DUE, "end_at": "2026-11-04T16:30:00+08:00"}]},
    {"request": REQUEST, "busy_slots": [{"start_at": REQUEST["end_at"], "end_at": "2026-11-04T17:00:00+08:00"}]},
    {"request": {**REQUEST, "title": 7}, "busy_slots": []},
    {"request": {**REQUEST, "title": "  "}, "busy_slots": []},
    {"request": {**REQUEST, "end_at": "2026-11-04T14:00:00+08:00"}, "busy_slots": []},
    {"request": {**REQUEST, "start_at": "2026-11-04T15:00:00"}, "busy_slots": []},
    {"request": {**REQUEST, "start_at": "2026-11-04T00:00:00+08:00", "end_at": "2026-11-04T00:30:00+08:00"},
     "busy_slots": [{"start_at": "2026-11-03T23:30:00+08:00", "end_at": "2026-11-04T01:00:00+08:00"}]},
    {"request": REQUEST, "busy_slots": [{"start_at": DUE, "end_at": "2026-11-04T18:00:00+08:00"}]},
    {"request": {k: v for k, v in REQUEST.items() if k != "title"}, "busy_slots": []},
    {"request": REQUEST, "busy_slots": [{}]},
]


@pytest.fixture(scope="module")
def historical_calendar(tmp_path_factory):
    root = tmp_path_factory.mktemp("historical-calendar")
    source = export_baseline(root / "baseline")
    inputs, output = root / "inputs.json", root / "output.json"
    inputs.write_text(json.dumps(CASES), encoding="utf-8")
    code = """
import json,sys
from productivity_agent.workflows.calendar import build_graph
from productivity_agent.workflows.calendar_replanning import propose_calendar_replan
cases=json.load(open(sys.argv[1],encoding='utf-8'))
results=[{'decision':build_graph().invoke(c)['result'],
          'proposal':propose_calendar_replan(c['request'],c['busy_slots'])} for c in cases]
with open(sys.argv[2],'w',encoding='utf-8') as f:json.dump(results,f)
"""
    subprocess.run([sys.executable, "-c", code, str(inputs), str(output)], cwd=root,
                   env=environment(source), capture_output=True, check=True, timeout=40)
    return json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("index", range(len(CASES)))
def test_graph_and_non_agent_calendar_match_fixed_old_source(historical_calendar, index):
    case = CASES[index]
    expected = historical_calendar[index]
    assert calendar.check_calendar(case["request"], case["busy_slots"]) == expected["decision"]
    assert build_graph().invoke(case)["result"] == expected["decision"]
    assert calendar.propose_calendar_replan(case["request"], case["busy_slots"]) == expected["proposal"]
    if index == 3:
        # Preserve the pre-existing Graph/Domain diagnostic distinction.
        assert "strip" in expected["decision"]["message"]
        assert assess_calendar(case["request"], [])["message"] == "Schedule title must be non-empty"


@pytest.mark.parametrize("remote", [False, True])
def test_shared_task_reads_keep_owner_scope_and_receipt_semantics(tmp_path, remote):
    tokens = {owner: secrets.token_hex(24) for owner in ["alice", "bob"]}
    auth = tmp_path / "accounts.json"
    auth.write_text(json.dumps({"users": {owner: {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}
                                          for owner, token in tokens.items()}}), encoding="utf-8")

    def exercise(store):
        alice = store.for_owner("alice", tokens["alice"])
        bob = store.for_owner("bob", tokens["bob"])
        first = alice.create_task("create", "real task", DUE)["task"]
        changed = alice.change_task("change", first["id"], 1, "complete_task")["task"]
        assert tasks.list_tasks(alice, limit=1000) == [changed]
        assert tasks.get_task(alice, first["id"]) == changed
        assert tasks.get_operation(alice, "create")["task"] == changed
        assert tasks.get_operation(alice, "change")["request"]["expected_version"] == 1
        assert tasks.list_tasks(bob) == []
        assert tasks.get_operation(bob, "create") is None
        with pytest.raises(KeyError):
            tasks.get_task(bob, first["id"])
        mock = MockProductivityBackend(tasks=[{"id": "mock-only", "title": "demo task"}])
        tools = {t.name: t for t in build_productivity_tools(mock)}
        assert json.loads(tools["list_tasks"].invoke({}))[0]["id"] == "mock-only"
        assert tasks.list_tasks(alice) == [changed]
        assert "create_task" not in tools

    if remote:
        with server("productivity_agent.api.task_service:create_task_service", tmp_path / "business", auth) as url:
            exercise(HTTPTaskStore(url))
    else:
        exercise(SQLiteTaskStore(tmp_path / "tasks.sqlite"))


def test_shared_operation_read_does_not_hide_unavailable_remote(service):
    store, _, root = service
    store.create_task("seed", "test", DUE)
    (root / "fault").write_text("read_5xx")
    with pytest.raises(BusinessUnavailable):
        tasks.get_operation(store, "seed")
    assert tasks.get_operation(store, "seed") is not None


def test_calendar_display_and_conflict_scope_are_separate_snapshots():
    backend = MockProductivityBackend(events=[{"title": "overnight", **CASES[7]["busy_slots"][0]}])
    assert calendar.calendar_events(backend, "2026-11-04") == []
    slots = calendar.calendar_busy_slots(backend)
    assert calendar.check_calendar(CASES[7]["request"], slots)["status"] == "conflict"
    slots[0]["end_at"] = "modified copy"
    assert backend.events[0]["end_at"] == "2026-11-04T01:00:00+08:00"


def test_use_cases_run_without_agent_http_or_graph_imports(tmp_path):
    code = """
import importlib.abc,sys
class BlockFrameworks(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('langgraph','langchain','fastapi','productivity_agent.application.agent',
                          'productivity_agent.workflows','productivity_agent.tools')):
   raise AssertionError('business reads imported framework/Agent: '+fullname)
sys.meta_path.insert(0,BlockFrameworks())
from productivity_agent.application.use_cases import tasks,calendar
from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
from productivity_agent.infrastructure.integrations.mock_productivity import MockProductivityBackend
store=SQLiteTaskStore(sys.argv[1]); task=store.create_task('seed','trusted fixture','2026-11-04T15:00:00+08:00')['task']
assert tasks.list_tasks(store)==[task]
assert tasks.get_task(store,task['id'])==task
assert tasks.get_operation(store,'seed')['task']==task
assert calendar.calendar_busy_slots(MockProductivityBackend())==[]
assert calendar.check_calendar({'title':'meeting','start_at':'2026-11-04T15:00:00+08:00',
 'end_at':'2026-11-04T16:00:00+08:00'},[])['status']=='available'
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path / "tasks.sqlite")],
                   check=True, capture_output=True, timeout=30)


def test_new_application_implementation_avoids_legacy_and_concrete_adapters():
    for path in (PACKAGE / "application").rglob("*.py"):
        modules = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(a.name for a in node.names)
        assert not any(m.startswith(("productivity_agent.infrastructure", "productivity_agent.services",
            "productivity_agent.providers", "productivity_agent.api", "productivity_agent.tools",
            "productivity_agent.workflows", "productivity_agent.domain.state", "productivity_agent.domain.intent"))
            for m in modules), path
        if path.relative_to(PACKAGE / "application").parts[0] in {"ports", "use_cases"}:
            assert not any(m.startswith(("fastapi", "langgraph", "langchain", "productivity_agent.application.agent"))
                           for m in modules), path


def test_migrated_legacy_symbols_are_aliases_of_single_implementations():
    for old, new, names in [
        ("domain.state", "application.agent.workflows.calendar", ["CalendarState"]),
        ("domain.intent", "application.agent.llm.contracts", ["ScheduleIntent"]),
        ("domain.intent", "application.agent.llm.normalization", ["normalize_schedule_intent"]),
        ("workflows.calendar", "application.agent.workflows.calendar", ["build_graph", "validate_request"]),
        ("workflows.natural_language", "application.agent.workflows.natural_language", ["build_natural_language_graph"]),
        ("workflows.tool_agent", "application.agent.workflows.tool_agent", ["build_tool_agent"]),
        ("tools.productivity", "infrastructure.integrations.mock_productivity", ["MockProductivityBackend"]),
        ("tools.productivity", "application.agent.tools.productivity", ["build_productivity_tools"]),
    ]:
        legacy, actual = [importlib.import_module("productivity_agent." + module) for module in (old, new)]
        for name in names:
            assert getattr(legacy, name) is getattr(actual, name)


def test_fixed_old_source_nested_read_checkpoint_recovery(tmp_path):
    report = verify(tmp_path)
    path = REPO / "reports/r2-b1/nested-read-compatibility.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert set(report["cases"]) == {"assistant-legacy", "assistant-auth", "natural", "tool"}
    assert report["live_model_calls"] == 0

"""Non-Agent creation against a fixed-old Graph oracle and real Adapter faults."""
import hashlib
import importlib
import json
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from helpers.creation_oracle import CASES, DUE, observe
from test_task07_security import server

from productivity_agent.application.ports.tasks import AmbiguousCommitError, TransientWriteError
from productivity_agent.application.use_cases.task_creation import (
    create_task_reliably,
    verify_created_task,
)
from productivity_agent.infrastructure.integrations.http_task_store import (
    BusinessUnavailable,
    HTTPTaskStore,
)
from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
from scripts.verify_r2_b2_creation import verify
from scripts.verify_r2_baseline import environment, export_baseline

pytest_plugins = ["test_task06_operations"]
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def historical_creation(tmp_path_factory):
    root = tmp_path_factory.mktemp("old-creation")
    source = export_baseline(root / "baseline")
    output = root / "observations.json"
    subprocess.run([sys.executable, str(REPO / "tests/helpers/creation_oracle.py"),
                    str(root / "business"), str(output)], cwd=root, env=environment(source),
                   capture_output=True, check=True, timeout=60)
    return json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES)
def test_framework_free_creation_and_graph_match_fixed_old_policy(historical_creation, tmp_path, case):
    for direct in [False, True]:
        root = tmp_path / str(direct)
        root.mkdir()
        assert observe(root, case, direct=direct) == historical_creation[case]


@pytest.mark.parametrize("approved", [False, None, 1, "true"])
def test_independent_creation_requires_explicit_trusted_boolean_approval(tmp_path, approved):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    if approved is False:
        assert create_task_reliably(store, "op", "task", DUE, approved=False)["status"] == "cancelled"
    else:
        with pytest.raises(ValueError, match="approved must be a boolean"):
            create_task_reliably(store, "op", "task", DUE, approved=approved)
    assert store.count_tasks() == 0
    assert store.get_operation("op") is None


@pytest.mark.parametrize("fault", ["500", "before_timeout", "after_timeout", "after_5xx",
                                  "after_timeout_read_5xx"])
def test_non_agent_real_http_reconciliation_preserves_unknown_results(service, fault):
    stable, url, root = service
    (root / "fault").write_text(fault)
    fast = HTTPTaskStore(url, timeout=0.15)
    if fault == "after_timeout_read_5xx":
        with pytest.raises(BusinessUnavailable):
            create_task_reliably(fast, "op", "task", DUE, approved=True)
    else:
        result = create_task_reliably(fast, "op", "task", DUE, approved=True)
        assert result["status"] == ("recovered" if fault.startswith("after") else "created")
        assert result["attempts"] == (1 if fault.startswith("after") else 2)
    task = stable.lookup("op", "task", DUE)
    assert task is not None and task["version"] == 1
    assert len(stable.list_tasks()) == 1
    # Transport requests may replay; the durable operation and Task remain one.
    assert len((root / "write-requests.txt").read_text().splitlines()) == (
        1 if fault.startswith("after") else 2)


def test_verification_checks_durable_id_and_does_not_swallow_read_errors(tmp_path, service):
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite")
    result = create_task_reliably(store, "op", "task", DUE, approved=True)
    assert verify_created_task(store, "op", "task", DUE, result) == result["task"]
    assert verify_created_task(store, "missing", "task", DUE, result) is None
    assert verify_created_task(store, "op", "task", DUE, {"task": {"id": "wrong"}}) is None
    remote, _, root = service
    remote.create_task("op", "task", DUE)
    (root / "fault").write_text("read_5xx")
    with pytest.raises(BusinessUnavailable):
        verify_created_task(remote, "op", "task", DUE, result)


def test_migrated_symbols_and_error_catches_share_single_implementations():
    for old, new, names in [
        ("workflows.reliable_task", "application.agent.workflows.reliable_task",
         ["ReliableTaskState", "build_reliable_task_graph"]),
        ("workflows.approval_session", "application.agent.workflows.approval_session",
         ["ApprovalState", "build_approval_graph", "request_task_approval"]),
        ("tools.reliable_task", "application.agent.tools.reliable_task", ["build_safe_create_task_tool"]),
    ]:
        a, b = [importlib.import_module("productivity_agent." + mod) for mod in [old, new]]
        for name in names:
            assert getattr(a, name) is getattr(b, name)
    for name in ["services.task_store", "infrastructure.persistence.task_store"]:
        module = importlib.import_module("productivity_agent." + name)
        assert module.AmbiguousCommitError is AmbiguousCommitError
        assert module.TransientWriteError is TransientWriteError


def test_creation_works_without_agent_or_framework_imports(tmp_path):
    code = """
import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('langgraph','langchain','fastapi','productivity_agent.application.agent',
                          'productivity_agent.workflows','productivity_agent.tools')):
   raise AssertionError('creation depends on framework: '+fullname)
sys.meta_path.insert(0,Block())
from productivity_agent.application.use_cases.task_creation import create_task_reliably
from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
store=SQLiteTaskStore(sys.argv[1]); args=(store,'op','task','2026-11-04T15:00:00+08:00')
first=create_task_reliably(*args,approved=True)
second=create_task_reliably(*args,approved=True)
assert first['task']==second['task'] and second['status']=='recovered'
assert store.count_tasks()==1
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path / "tasks.sqlite")],
                   capture_output=True, check=True, timeout=30)


@pytest.mark.parametrize("remote", [False, True])
def test_creation_scope_is_bound_by_caller_and_same_operation_isolated(tmp_path, remote):
    tokens = {owner: secrets.token_hex(24) for owner in ["alice", "bob"]}
    auth = tmp_path / "accounts.json"
    auth.write_text(json.dumps({"users": {owner: {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}
                                          for owner, token in tokens.items()}}), encoding="utf-8")

    def exercise(store):
        results = []
        for owner, token in tokens.items():
            bound = store.for_owner(owner, token)
            created = create_task_reliably(bound, "shared-op", owner, DUE, approved=True)
            replay = create_task_reliably(bound, "shared-op", owner, DUE, approved=True)
            assert created["task"] == replay["task"] and replay["status"] == "recovered"
            assert bound.list_tasks() == [created["task"]]
            results.append(created["task"])
        assert results[0]["id"] != results[1]["id"]
        with pytest.raises(KeyError):
            store.for_owner("bob", tokens["bob"]).get_task(results[0]["id"])

    if remote:
        with server("productivity_agent.api.task_service:create_task_service", tmp_path / "business", auth) as url:
            exercise(HTTPTaskStore(url))
    else:
        exercise(SQLiteTaskStore(tmp_path / "tasks.sqlite"))


def test_minimal_production_port_does_not_require_fault_parameter(tmp_path):
    from productivity_agent.application.agent.workflows.reliable_task import (
        build_reliable_task_graph,
    )

    class OrdinaryStore(SQLiteTaskStore):
        def create_task(self, operation_id, title, due_at):
            return super().create_task(operation_id, title, due_at)

    store = OrdinaryStore(tmp_path / "tasks.sqlite")
    args = {"operation_id": "op", "title": "task", "due_at": DUE}
    assert build_reliable_task_graph(store).invoke(args)["status"] == "created"
    assert create_task_reliably(store, **args, approved=True)["status"] == "recovered"
    assert store.count_tasks() == 1


def test_fixed_old_intermediate_creation_checkpoints(tmp_path):
    report = verify(tmp_path)
    path = REPO / "reports/r2-b2/intermediate-creation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert len(report["cases"]) == 4
    assert report["live_model_calls"] == 0

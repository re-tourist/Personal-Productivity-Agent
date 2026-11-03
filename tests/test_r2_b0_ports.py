"""Preserve observed adapter differences; this file does not repair their policy."""
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from test_task06_operations import DUE, approve, say

from productivity_agent.api.app import create_app
from productivity_agent.domain.tasks import IdempotencyConflict, VersionConflict
from productivity_agent.infrastructure.integrations.http_task_store import (
    BusinessUnavailable,
    HTTPTaskStore,
)
from productivity_agent.infrastructure.persistence.task_store import (
    AmbiguousCommitError,
    SQLiteTaskStore,
)
from productivity_agent.infrastructure.persistence.thread_ownership import ThreadOwnership
from productivity_agent.tools.productivity import MockProductivityBackend, build_productivity_tools
from productivity_agent.workflows.reliable_task import build_reliable_task_graph

pytest_plugins = ["test_task06_operations"]


@pytest.mark.parametrize("remote", [False, True])
def test_conflicts_and_asymmetric_historical_receipts(service, tmp_path, remote):
    store, url, _ = service
    if not remote:
        store = SQLiteTaskStore(tmp_path / "local.sqlite")
    created = store.create_task("create", "original", DUE)["task"]
    with pytest.raises(VersionConflict if remote else IdempotencyConflict):
        store.create_task("create", "different", DUE)
    changed = store.change_task("change", created["id"], 1, "update_task", title="second")["task"]
    final = store.change_task("finish", created["id"], 2, "complete_task")["task"]
    assert final["version"] == 3
    # Creation replays/lookup/receipts use the current task, despite original parameters.
    assert store.create_task("create", "original", DUE)["task"] == final
    assert store.lookup("create", "original", DUE) == final
    creation_receipt = store.get_operation("create")
    assert creation_receipt["task"] == final
    assert "request_hash" in creation_receipt and "request" not in creation_receipt
    # Changes preserve the historical result and replay BEFORE checking version.
    assert store.change_task("change", created["id"], 1, "update_task", title="second")["task"] == changed
    change_receipt = store.get_operation("change")
    assert change_receipt["task"] == changed
    assert change_receipt["request"]["expected_version"] == 1
    with pytest.raises(VersionConflict if remote else IdempotencyConflict):
        store.change_task("change", created["id"], 1, "update_task", title="different")
    with pytest.raises(VersionConflict):
        store.change_task("stale", created["id"], 1, "complete_task")
    assert store.get_task(created["id"]) == final
    assert store.get_operation("missing") is None
    with pytest.raises(KeyError):
        store.get_task("missing")
    if remote:
        with httpx.Client(base_url=url, trust_env=False) as client:
            response = client.post("/tasks", json={"operation_id": "create", "title": "different",
                                                   "due_at": DUE, "approved": True})
            assert response.status_code == 409
            assert response.json() == {"detail": "conflict_read_again"}


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("fault", ["500", "before_timeout", "after_timeout", "after_5xx"])
def test_real_http_write_fault_classification(service, action, fault):
    stable, url, root = service
    task = stable.create_task("seed", "seed", DUE)["task"]
    fast = HTTPTaskStore(url, timeout=0.15)
    (root / "fault").write_text(fault)
    error = BusinessUnavailable if action == "update" and fault in {"500", "after_5xx"} else AmbiguousCommitError
    with pytest.raises(error):
        if action == "create":
            fast.create_task("write", "new", DUE)
        else:
            fast.change_task("write", task["id"], 1, "update_task", title="new")
    receipt = stable.get_operation("write")
    committed = fault in {"after_timeout", "after_5xx"}
    assert (receipt is not None) == committed
    assert len(stable.list_tasks()) == (2 if committed and action == "create" else 1)
    assert stable.get_task(task["id"])["version"] == (2 if committed and action == "update" else 1)
    assert len((root / "write-requests.txt").read_text().splitlines()) == 2  # seed + one uncertain write


@pytest.mark.parametrize("fault", ["read_5xx", "read_timeout"])
def test_failed_reconciliation_read_is_not_missing(service, fault):
    stable, url, root = service
    stable.create_task("committed", "seed", DUE)
    (root / "fault").write_text(fault)
    with pytest.raises(BusinessUnavailable):
        HTTPTaskStore(url, timeout=0.15).get_operation("committed")
    assert stable.get_operation("committed") is not None
    assert stable.get_operation("actually_missing") is None


def test_m4_unknown_commit_with_failed_read_propagates(service):
    stable, url, root = service
    (root / "fault").write_text("after_timeout_read_5xx")
    # This gap is an existing exception-family asymmetry, NOT proof of no commit.
    with pytest.raises(BusinessUnavailable):
        build_reliable_task_graph(HTTPTaskStore(url, timeout=0.15)).invoke({
            "operation_id": "m4-unknown", "title": "seed", "due_at": DUE})
    assert stable.get_operation("m4-unknown")["task"]["version"] == 1
    assert len(stable.list_tasks()) == 1
    assert len((root / "write-requests.txt").read_text().splitlines()) == 1


@pytest.mark.parametrize("kind", ["assistant_create", "assistant_update", "draft"])
def test_unknown_commit_never_reported_as_unexecuted(service, tmp_path, monkeypatch, kind):
    stable, url, root = service
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path / "assistant"))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", url)
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    monkeypatch.setenv("PPA_AUTH_CONFIG", "")
    original = HTTPTaskStore.__init__

    def fast(self, base_url, *args, **kwargs):
        original(self, base_url, timeout=0.15, **kwargs)

    monkeypatch.setattr(HTTPTaskStore, "__init__", fast)
    with TestClient(create_app(api_token=""), raise_server_exceptions=False) as api:
        if kind == "draft":
            pending = api.post("/v1/tasks/drafts", json={"title": "draft", "due_at": DUE}).json()
            tid = pending["thread_id"]
            op = pending["approval"]["operation_id"]
        else:
            tid = api.post("/v1/assistant/sessions").json()["thread_id"]
            if kind == "assistant_update":
                task = stable.create_task("seed", "seed", DUE)["task"]
                pending = say(api, tid, f"把{task['id']}改为new")
            else:
                pending = say(api, tid, "明天下午三点提醒我故障证据")
            op = pending["approval"]["operation_id"]
        (root / "fault").write_text("after_timeout_read_5xx")
        if kind == "draft":
            response = api.post(f"/v1/tasks/drafts/{tid}/decision", json={"approved": True})
            assert response.status_code == 500
            assert api.post(f"/v1/tasks/drafts/{tid}/decision", json={"approved": True}).status_code == 409
            snapshot = api.get(f"/v1/tasks/drafts/{tid}").json()
            assert snapshot["status"] == "approved" and snapshot["task"] is None
        else:
            outcome = approve(api, tid, pending)
            assert outcome["status"] == "needs_review" and outcome["result"] is None
        receipt = stable.get_operation(op)
        assert receipt["task"]["version"] == (2 if kind == "assistant_update" else 1)
        assert len(stable.list_tasks()) == 1
        assert len((root / "write-requests.txt").read_text().splitlines()) == (2 if kind == "assistant_update" else 1)
        (root / "observed.json").write_text(json.dumps({"kind": kind, "committed_receipt": receipt,
            "response": snapshot if kind == "draft" else outcome}, ensure_ascii=False), encoding="utf-8")


def test_calendar_display_filter_does_not_reduce_conflict_input():
    backend = MockProductivityBackend(events=[{
        "title": "overnight", "start_at": "2026-11-02T23:30:00+08:00",
        "end_at": "2026-11-03T01:00:00+08:00"}])
    tools = {tool.name: tool for tool in build_productivity_tools(backend)}
    assert json.loads(tools["list_calendar_events"].invoke({"date_iso": "2026-11-03"})) == []
    result = tools["check_calendar_conflict"].invoke({"title": "candidate",
        "start_at": "2026-11-03T00:00:00+08:00", "end_at": "2026-11-03T00:30:00+08:00"})
    assert result["status"] == "conflict"


@pytest.mark.parametrize("second_owner", ["owner", "other"])
def test_duplicate_thread_claim_preserves_original_and_raises(tmp_path, second_owner):
    ownership = ThreadOwnership(tmp_path / "access.sqlite")
    ownership.claim("assistant", "thread", "owner")
    with pytest.raises(sqlite3.IntegrityError):
        ownership.claim("assistant", "thread", second_owner)
    assert ownership.owns("assistant", "thread", "owner")
    assert not ownership.owns("assistant", "thread", "other")

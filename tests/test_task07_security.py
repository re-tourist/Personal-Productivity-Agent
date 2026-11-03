"""Two accounts, real graphs/SQLite, and two independent HTTP processes. No model calls."""
import hashlib
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app
from productivity_agent.services.http_task_store import BusinessUnavailable, HTTPTaskStore
from productivity_agent.services.identity import LEGACY_OWNER, Accounts
from productivity_agent.services.task_store import SQLiteTaskStore


class CredentialHeaders(dict):
    def __repr__(self):
        return "<synthetic authorization redacted>"


NOW = "2026-11-03T12:00:00+08:00"
DUE = "2026-11-04T15:00:00+08:00"


@contextmanager
def server(module, directory, auth, *, port=None, **extra):
    directory.mkdir(parents=True, exist_ok=True)
    if port is None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    env = dict(os.environ, PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="", PPA_API_TOKEN="",
               PPA_DATA_DIR=str(directory), PPA_AUTH_CONFIG=str(auth) if auth else "", LANGSMITH_TRACING="false",
               PPA_TASK_SERVICE_URL="")
    env.update(extra)
    with (directory / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--factory",
                                    "--host", "127.0.0.1", "--port", str(port)],
                                   env=env, stdout=log, stderr=log)
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 25
            while True:
                assert process.poll() is None, "test server exited; inspect private synthetic log"
                try:
                    if httpx.get(url + "/health", trust_env=False, timeout=0.3).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "test server readiness timeout"
                time.sleep(0.05)
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(params=["direct", "http"])
def secured(request, tmp_path, monkeypatch):
    tokens = {owner: secrets.token_urlsafe(32) for owner in ("alice", "bob")}
    auth = tmp_path / "accounts.json"
    auth.write_text(json.dumps({"users": {owner: {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}
                                          for owner, token in tokens.items()}}), encoding="utf-8")
    headers = {owner: CredentialHeaders(Authorization="Bearer " + token) for owner, token in tokens.items()}
    agent = tmp_path / "agent"
    monkeypatch.setenv("PPA_AUTH_CONFIG", str(auth))
    monkeypatch.setenv("PPA_DATA_DIR", str(agent))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")

    @contextmanager
    def client():
        if request.param == "direct":
            with TestClient(create_app(api_token="")) as api:
                yield api, None
        else:
            with (
                server("productivity_agent.api.task_service:create_task_service", tmp_path / "business", auth) as url,
                server("productivity_agent.api.app:create_app", agent, auth, PPA_TASK_SERVICE_URL=url) as agent_url,
                httpx.Client(base_url=agent_url, trust_env=False, timeout=15) as api,
            ):
                yield api, url

    path = agent / "tasks.sqlite" if request.param == "direct" else tmp_path / "business/tasks.sqlite"
    return client, headers, path


def session(api, h):
    response = api.post("/v1/assistant/sessions", headers=h)
    assert response.status_code == 201
    return response.json()["thread_id"]


def say(api, h, tid, text, *, stream=False):
    path = f"/v1/assistant/sessions/{tid}/messages" + ("/stream" if stream else "")
    return api.post(path, headers=h, json={"message": text, "reference_now": NOW,
                    "timezone": "Asia/Shanghai", "message_id": str(uuid.uuid4())})


def decision(api, h, tid, pending, approved=True):
    return api.post(f"/v1/assistant/sessions/{tid}/decision", headers=h, json={
        "operation_id": pending["approval"]["operation_id"], "approved": approved})


def create(api, h, title="同名任务"):
    tid = session(api, h)
    pending = say(api, h, tid, f"明天下午三点提醒我{title}").json()
    response = decision(api, h, tid, pending)
    assert response.json()["status"] == "created", response.text
    return tid, pending, response.json()["result"]["task"]


def test_two_account_resource_thread_operation_and_sse_isolation(secured):
    factory, h, path = secured
    with factory() as (api, business_url):
        a, b = h["alice"], h["bob"]
        assert api.get("/v1/tasks").status_code == 401
        assert api.get("/v1/tasks", headers={"X-User-ID": "alice"}).status_code == 401
        assert api.get("/v1/me", headers={**b, "X-User-ID": "alice"}).json()["owner_id"] == "bob"
        assert api.post("/v1/tasks/drafts", headers=b, json={"title": "forged", "due_at": DUE,
                                                            "owner_id": "alice"}).status_code == 422
        tid = session(api, a)
        pending = say(api, a, tid, "明天下午三点提醒我同名任务").json()
        operation = pending["approval"]["operation_id"]
        for response in [
            api.get(f"/v1/assistant/sessions/{tid}", headers=b),
            api.post(f"/v1/assistant/sessions/{tid}/recover", headers=b),
            decision(api, b, tid, pending),
            say(api, b, tid, "查看我的任务"),
            say(api, b, tid, "查看我的任务", stream=True),
        ]:
            assert response.status_code == 404
            assert "同名任务" not in response.text and operation not in response.text
        assert decision(api, a, tid, pending).json()["status"] == "created"
        task = api.get("/v1/tasks", headers=a).json()["items"][0]
        assert api.get(f"/v1/tasks/{task['id']}", headers=b).status_code == 404
        assert api.get(f"/v1/operations/{operation}", headers=b).status_code == 404
        assert api.get(f"/v1/operations/{operation}", headers=a).json()["operation"]["task"]["id"] == task["id"]
        assert api.get("/v1/tasks", headers=b).json()["items"] == []
        btid = session(api, b)
        denied = say(api, b, btid, f"把{task['id']}改为偷改").json()
        assert denied["status"] == "not_found" and denied["approval"] is None
        _, _, other = create(api, b)
        assert other["id"] != task["id"]
        assert [t["id"] for t in api.get("/v1/tasks", headers=b).json()["items"]] == [other["id"]]
        own_stream = say(api, b, session(api, b), "查看我的任务", stream=True)
        assert own_stream.status_code == 200 and "event: done" in own_stream.text
        assert other["id"] in own_stream.text and task["id"] not in own_stream.text
        draft = api.post("/v1/tasks/drafts", headers=a, json={"title": "private-draft", "due_at": DUE}).json()
        dtid = draft["thread_id"]
        assert api.get(f"/v1/tasks/drafts/{dtid}", headers=b).status_code == 404
        assert api.post(f"/v1/tasks/drafts/{dtid}/decision", headers=b, json={"approved": True}).status_code == 404
        assert api.get(f"/v1/tasks/drafts/{dtid}", headers=a).status_code == 200
        if business_url:
            confused = HTTPTaskStore(business_url).for_owner("alice", b["Authorization"][7:])
            with pytest.raises(BusinessUnavailable):
                confused.change_task("confused", task["id"], 1, "complete_task")
            with httpx.Client(base_url=business_url, trust_env=False) as service:
                assert service.get(f"/tasks/{task['id']}", headers=b).status_code == 404
                assert service.get(f"/operations/{operation}", headers=b).json()["operation"] is None
                denied = service.patch(f"/tasks/{task['id']}", headers=b, json={
                    "operation_id": operation, "approved": True, "expected_version": 1,
                    "action": "complete_task"})
                assert denied.status_code == 404
        with sqlite3.connect(path) as conn:
            assert sorted(conn.execute("SELECT owner_id,COUNT(*) FROM tasks GROUP BY owner_id").fetchall()) == [("alice", 1), ("bob", 1)]


def test_same_user_concurrent_approval_and_real_restart(secured):
    factory, h, path = secured
    with factory() as (api, _):
        a, b = h["alice"], h["bob"]
        tid, _, task = create(api, a, "并发任务")
        other = session(api, a)
        p1 = say(api, a, tid, f"把{task['id']}改为版本甲").json()
        p2 = say(api, a, other, f"把{task['id']}改为版本乙").json()
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(decision, api, a, t, p) for t, p in [(tid, p1), (other, p2)]]
            statuses = sorted(f.result().json()["status"] for f in futures)
        assert statuses == ["conflict", "updated"]
        current = api.get(f"/v1/tasks/{task['id']}", headers=a).json()
        assert current["version"] == 2
        pending = say(api, a, tid, f"完成任务 {task['id']}").json()
        assert pending["approval"]
    # Both production servers really exit and restart in HTTP mode; metadata and checkpoints persist.
    with factory() as (api, _):
        assert api.get(f"/v1/assistant/sessions/{tid}", headers=b).status_code == 404
        assert api.post(f"/v1/assistant/sessions/{tid}/recover", headers=b).status_code == 404
        assert decision(api, b, tid, pending).status_code == 404
        result = decision(api, a, tid, pending).json()
        assert result["result"]["task"]["status"] == "completed"
        assert decision(api, a, tid, pending).json() == result
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT owner_id,status,version FROM tasks").fetchall() == [("alice", "completed", 3)]


def test_owner_namespace_and_legacy_quarantine(tmp_path):
    path = tmp_path / "tasks.sqlite"
    store = SQLiteTaskStore(path)
    old = store.create_task("same", "legacy", DUE)["task"]
    a, b = store.for_owner("alice"), store.for_owner("bob")
    first = a.create_task("same", "own", DUE)["task"]
    second = b.create_task("same", "own", DUE)["task"]
    assert a.create_task("same", "own", DUE)["status"] == "replayed"
    assert a.get_operation("same")["task"]["id"] == first["id"]
    assert b.get_operation("same")["task"]["id"] == second["id"]
    with pytest.raises(KeyError):
        b.change_task("same", first["id"], 1, "complete_task")
    assert len(a.list_tasks()) == len(b.list_tasks()) == 1
    with pytest.raises(KeyError):
        a.get_task(old["id"])
    assert SQLiteTaskStore(path).get_task(old["id"])["title"] == "legacy"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT owner_id FROM tasks WHERE id=?", (old["id"],)).fetchone()[0] == LEGACY_OWNER


def test_bad_auth_configuration_fails_closed(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"users":{}}')
    with pytest.raises(ValueError):
        Accounts(path)
    with pytest.raises(ValueError):
        HTTPTaskStore("https://example.com", bearer="synthetic", expected_owner="alice")


def test_secure_adapter_refuses_unauthenticated_business_service(tmp_path):
    with server("productivity_agent.api.task_service:create_task_service", tmp_path / "legacy", None) as url:
        store = HTTPTaskStore(url).for_owner("alice", secrets.token_urlsafe(32))
        with pytest.raises(BusinessUnavailable):
            store.change_task("denied", "absent", 1, "complete_task")
    assert SQLiteTaskStore(tmp_path / "legacy/tasks.sqlite").count_tasks() == 0


def test_pre_owner_data_and_unbound_threads_are_quarantined(tmp_path, monkeypatch):
    from productivity_agent.services.task_store import request_fingerprint
    path = tmp_path / "tasks.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,due_at TEXT);"
                           "CREATE TABLE task_operations(operation_id TEXT PRIMARY KEY,request_hash TEXT,task_id TEXT);")
        conn.execute("INSERT INTO tasks VALUES ('old','private-legacy',?)", (DUE,))
        digest = request_fingerprint("private-legacy", "2026-11-04T07:00:00+00:00")
        conn.execute("INSERT INTO task_operations VALUES ('historic',?,'old')", (digest,))
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    monkeypatch.setenv("PPA_AUTH_CONFIG", "")
    with TestClient(create_app(api_token="")) as api:
        old_thread = session(api, {})
    token = secrets.token_urlsafe(32)
    auth = tmp_path / "accounts.json"
    auth.write_text(json.dumps({"users": {"alice": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}}}))
    monkeypatch.setenv("PPA_AUTH_CONFIG", str(auth))
    h = CredentialHeaders(Authorization="Bearer " + token)
    with TestClient(create_app(api_token="")) as api:
        assert api.get("/v1/tasks", headers=h).json()["items"] == []
        assert api.get("/v1/tasks/old", headers=h).status_code == 404
        assert api.get("/v1/operations/historic", headers=h).status_code == 404
        assert api.get(f"/v1/assistant/sessions/{old_thread}", headers=h).status_code == 404
        assert api.post(f"/v1/assistant/sessions/{old_thread}/recover", headers=h).status_code == 404
    assert SQLiteTaskStore(path).lookup("historic", "private-legacy", DUE)["id"] == "old"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT owner_id FROM tasks WHERE id='old'").fetchone() == (LEGACY_OWNER,)
        assert conn.execute("SELECT * FROM task_operations").fetchall() == [("historic", digest, "old")]


def test_account_setup_never_prints_or_overwrites_tokens(tmp_path):
    command = [sys.executable, "-m", "scripts.setup_test_accounts", "--out-dir", str(tmp_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
    tokens = json.loads((tmp_path / "client-tokens.auth.json").read_text())
    assert all(token not in result.stdout + result.stderr for token in tokens.values())
    accounts = Accounts(tmp_path / "accounts.auth.json")
    assert accounts.authenticate("Bearer " + tokens["alice"]).owner_id == "alice"
    before = (tmp_path / "client-tokens.auth.json").read_bytes()
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert (tmp_path / "client-tokens.auth.json").read_bytes() == before

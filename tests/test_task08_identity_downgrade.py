"""Real same-address service restart: an authenticated client must fail closed."""
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from test_task07_security import DUE, CredentialHeaders, server

from productivity_agent.services.http_task_store import BusinessUnavailable, HTTPTaskStore
from productivity_agent.services.task_store import AmbiguousCommitError, SQLiteTaskStore


def test_same_client_rejects_service_restart_into_legacy(tmp_path):
    token = secrets.token_urlsafe(32)
    auth = tmp_path / "accounts.auth.json"
    auth.write_text(json.dumps({"users": {"alice": {
        "token_sha256": hashlib.sha256(token.encode()).hexdigest()}}}), encoding="utf-8")
    directory = tmp_path / "business"
    raw = SQLiteTaskStore(directory / "tasks.sqlite")
    raw.create_task("legacy", "private-legacy-marker", DUE)
    with server("productivity_agent.api.task_service:create_task_service", directory, auth) as url:
        client = HTTPTaskStore(url).for_owner("alice", token)
        own = client.create_task("create", "alice-only", DUE)["task"]
        assert client.list_tasks() == [own]
        port = urlsplit(url).port
    with server("productivity_agent.api.task_service:create_task_service", directory, None, port=port) as restarted:
        assert restarted == url
        with pytest.raises(BusinessUnavailable):
            client.list_tasks()
        with pytest.raises(AmbiguousCommitError):
            client.create_task("after-restart", "must-not-write", DUE)
        assert raw.count_tasks() == 1
        assert raw.for_owner("alice").list_tasks() == [own]


def test_legacy_business_rejects_bearer_but_preserves_anonymous_demo(tmp_path):
    with server("productivity_agent.api.task_service:create_task_service", tmp_path, None) as url:
        h = CredentialHeaders(Authorization="Bearer " + secrets.token_urlsafe(32))
        payload = {"operation_id": "denied", "title": "must-not-write", "due_at": DUE,
                   "approved": True}
        with httpx.Client(base_url=url, trust_env=False) as api:
            assert api.get("/tasks", headers=h).status_code == 401
            assert api.post("/tasks", headers=h, json=payload).status_code == 401
        assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 0
        assert HTTPTaskStore(url).create_task("demo", "legacy-demo", DUE)["status"] == "created"


def test_identity_downgrade_between_preflight_and_write_is_rejected(tmp_path):
    token = secrets.token_urlsafe(32)
    auth = tmp_path / "accounts.auth.json"
    auth.write_text(json.dumps({"users": {"alice": {
        "token_sha256": hashlib.sha256(token.encode()).hexdigest()}}}), encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, PPA_AUTH_CONFIG=str(auth), PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="")
    helper = Path(__file__).parent / "helpers/business_server.py"
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(helper), str(tmp_path), str(port)],
                                   env=env, stdout=log, stderr=log)
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None
                try:
                    if httpx.get(url + "/health", trust_env=False, timeout=0.3).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline
                time.sleep(0.05)
            client = HTTPTaskStore(url).for_owner("alice", token)
            (tmp_path / "fault").write_text("identity_downgrade")
            # The identity GET succeeds, then the real POST reaches a legacy service.
            with pytest.raises(AmbiguousCommitError):
                client.create_task("race", "must-not-write", DUE)
            assert SQLiteTaskStore(tmp_path / "tasks.sqlite").count_tasks() == 0
            assert SQLiteTaskStore(tmp_path / "tasks.sqlite").for_owner("alice").count_tasks() == 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

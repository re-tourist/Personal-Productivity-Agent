"""Offline-model portfolio smoke: real authenticated HTTP and persistent process restarts."""
import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx


@contextmanager
def serve(python, root, auth, report):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="", PPA_API_TOKEN="",
               PPA_DATA_DIR=str(root / "data"), PPA_AUTH_CONFIG=str(auth),
               PPA_TASK_SERVICE_URL="", LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    number = len(report["processes"]) + 1
    with (root / f"runtime-{number}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([python, "-m", "uvicorn", "productivity_agent.api.app:create_app",
            "--factory", "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
            env=env, stdout=log, stderr=log)
        report["processes"].append({"pid": process.pid, "workers": 1, "binding": "loopback"})
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("local_server_readiness_failed")
                try:
                    if httpx.get(url + "/health", trust_env=False, timeout=0.3).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            with httpx.Client(base_url=url, trust_env=False, timeout=15) as api:
                yield api
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            report["processes"][-1]["stopped"] = process.poll() is not None


def verify(python, root, report):
    setup = subprocess.run([python, "-m", "scripts.setup_test_accounts", "--out-dir", str(root / "auth")],
                           capture_output=True, text=True, timeout=30, check=True)
    tokens = json.loads((root / "auth/client-tokens.auth.json").read_text(encoding="utf-8"))
    assert all(token not in setup.stdout + setup.stderr for token in tokens.values())
    auth = root / "auth/accounts.auth.json"
    a = {"Authorization": "Bearer " + tokens["alice"]}
    b = {"Authorization": "Bearer " + tokens["bob"]}
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    due = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    report["reference_now"] = now.isoformat()

    def say(api, tid, text):
        response = api.post(f"/v1/assistant/sessions/{tid}/messages", headers=a, json={
            "message": text, "reference_now": now.isoformat(), "timezone": "Asia/Shanghai",
            "message_id": str(uuid.uuid4())})
        assert response.status_code == 200
        return response.json()

    def decide(api, tid, pending, headers):
        return api.post(f"/v1/assistant/sessions/{tid}/decision", headers=headers, json={
            "operation_id": pending["approval"]["operation_id"], "approved": True})

    with serve(python, root, auth, report) as api:
        assert api.get("/v1/tasks").status_code == 401
        assert api.get("/v1/me", headers=a).json() == {"owner_id": "alice", "auth_enabled": True}
        system = api.get("/v1/system", headers=a).json()
        assert system["assistant_mode"] == "offline_rules" and system["live_qwen_enabled"] is False
        tid = api.post("/v1/assistant/sessions", headers=a).json()["thread_id"]
        pending = say(api, tid, "明天下午三点提醒我作品集验收")
        assert pending["status"] == "awaiting_approval"
        assert api.get("/v1/tasks", headers=a).json()["items"] == []
        assert decide(api, tid, pending, b).status_code == 404
        created = decide(api, tid, pending, a).json()
        assert created["status"] == "created"
        task = created["result"]["task"]
        assert api.get(f"/v1/tasks/{task['id']}", headers=a).json() == task
        assert api.get(f"/v1/tasks/{task['id']}", headers=b).status_code == 404
        report["created_task"] = task
        pending = say(api, tid, f"把{task['id']}改到后天上午十点")
        assert pending["status"] == "awaiting_approval"
        assert pending["approval"]["before"] == task
        report["pending_approval"] = pending["approval"]
    with serve(python, root, auth, report) as api:
        recovered = api.get(f"/v1/assistant/sessions/{tid}", headers=a).json()
        assert recovered["status"] == "awaiting_approval"
        assert recovered["approval"] == pending["approval"]
        assert api.post(f"/v1/assistant/sessions/{tid}/recover", headers=b).status_code == 404
        assert decide(api, tid, pending, b).status_code == 404
        updated = decide(api, tid, pending, a).json()
        assert updated["status"] == "updated"
        assert decide(api, tid, pending, a).json() == updated
        task = updated["result"]["task"]
        assert task["id"] == report["created_task"]["id"] and task["version"] == 2
        assert datetime.fromisoformat(task["due_at"]) == due
        queried = say(api, tid, f"查询任务 {task['id']}")
        assert queried["result"]["task"] == task
        assert api.get("/v1/tasks", headers=a).json()["items"] == [task]
        assert api.get("/v1/tasks", headers=b).json()["items"] == []
        report["updated_task"] = task
        report["pending_checkpoint_recovered"] = True
        report["duplicate_approval_unchanged"] = True
    with serve(python, root, auth, report) as api:
        assert api.get(f"/v1/tasks/{task['id']}", headers=a).json() == task
        restored = api.get(f"/v1/assistant/sessions/{tid}", headers=a).json()
        assert restored["result"]["task"] == task
        assert api.get(f"/v1/assistant/sessions/{tid}", headers=b).status_code == 404
        report["terminal_checkpoint_recovered"] = True
    with sqlite3.connect((root / "data/tasks.sqlite").as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT id,owner_id,title,due_at,status,version FROM tasks")]
    assert len(rows) == 1 and rows[0]["owner_id"] == "alice" and rows[0]["version"] == 2
    report["database_rows"] = rows
    assert len({p["pid"] for p in report["processes"]}) == 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Installed Python 3.12 runtime to verify")
    parser.add_argument("--out", type=Path, default=Path("reports/local-delivery.json"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    cache = repo / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    if cache.resolve() != cache or not cache.resolve().is_relative_to(repo):
        raise ValueError("unsafe_test_cache")
    root = Path(tempfile.mkdtemp(prefix="task08-delivery-", dir=cache))
    report = {"status": "RUNNING", "evidence_kind": "local_process_real_http_not_docker",
              "processes": [], "live_qwen_calls": 0, "cost_cny": 0,
              "private_work_directory_name": root.name}
    try:
        report["python_version"] = subprocess.check_output([
            args.python, "-c", "import platform; print(platform.python_version())"], text=True).strip()
        assert report["python_version"].startswith("3.12.")
        verify(args.python, root, report)
        report["status"] = "PASS"
    except Exception as exc:  # noqa: BLE001 -- no credentials or raw subprocess errors in reports.
        report["status"] = "FAIL"
        report["error_category"] = type(exc).__name__
    finally:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Local HTTP delivery: {report['status']}; Docker was not exercised; live model calls=0.")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

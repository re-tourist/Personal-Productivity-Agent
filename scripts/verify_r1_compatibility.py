"""Compare R1 HTTP contracts and resume synthetic data created by the baseline commit.

No user databases, credentials, or live models are used. Requires the repository's
Git history and installed dev dependencies; all runtime data stays in a fresh cache.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASELINE = "0ea0a340de5f43d0f234905930ba40c1d88cc62c"


def route_manifest(router):
    """Preserve registration order, including hidden routes and nested APIRouters.

    FastAPI versions may copy routes or retain an included router. All groups
    here declare their complete paths and use no include-time prefix override.
    """
    result = []
    for route in router.routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            result.extend(route_manifest(included))
        elif hasattr(route, "methods"):
            result.append({"path": route.path, "methods": sorted(route.methods or []),
                           "name": route.name, "operation_id": getattr(route, "operation_id", None)
                           or getattr(route, "unique_id", None)})
    return result


def snapshot(mode, root):
    from fastapi.testclient import TestClient

    if mode == "baseline":
        from productivity_agent.api.app import create_app
        from productivity_agent.api.task_service import create_task_service
        from productivity_agent.services.task_store import SQLiteTaskStore
    else:
        from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
        from productivity_agent.interfaces.http.assistant_app import create_app
        from productivity_agent.interfaces.http.business_app import create_task_service

    import productivity_agent

    if mode == "baseline":
        assert Path(productivity_agent.__file__).resolve().is_relative_to(root / "baseline")
    else:
        assert not Path(productivity_agent.__file__).resolve().is_relative_to(root / "baseline")
    assistant = create_app(api_token="")
    business = create_task_service(SQLiteTaskStore(root / "business.sqlite"))
    result = {"assistant_openapi": assistant.openapi(), "business_openapi": business.openapi(),
              "assistant_routes": route_manifest(assistant), "business_routes": route_manifest(business)}
    with TestClient(assistant) as api, TestClient(business) as service:
        page = api.get("/app")
        assert page.status_code == 200
        result["page_sha256"] = hashlib.sha256(page.content).hexdigest()
        redirect = api.get("/", follow_redirects=False)
        result["root_redirect"] = [redirect.status_code, redirect.headers["location"]]
        result["disabled_agent"] = api.post("/v1/agent/ask", json={
            "message": "offline", "reference_now": "2026-11-03T12:00:00+08:00"}).json()
        calendar = {"request": {"title": "compatibility-calendar", "start_at": "2026-12-10T15:00:00+08:00",
                                "end_at": "2026-12-10T16:00:00+08:00"}, "busy_slots": []}
        checked = api.post("/v1/calendar/check", json=calendar)
        assert checked.status_code == 200
        result["calendar_json"] = checked.json()
        streamed = api.post("/v1/calendar/check/stream", json=calendar)
        assert streamed.status_code == 200
        result["calendar_sse"] = {"body": streamed.text, "headers": {
            key: streamed.headers[key] for key in ("content-type", "cache-control", "x-accel-buffering")}}
        assert service.get("/health").status_code == 200
        result["business_bad_request"] = service.post("/tasks", json={}).json()
        assert service.post("/tasks", json={}).status_code == 400
        if mode == "baseline":
            first = api.post("/v1/tasks/drafts", json={
                "title": "existing-db-task", "due_at": "2026-12-10T15:00:00+08:00"})
            assert first.status_code == 201
            created = api.post(f"/v1/tasks/drafts/{first.json()['thread_id']}/decision",
                               json={"approved": True})
            assert created.status_code == 200 and created.json()["status"] == "created"
            pending = api.post("/v1/tasks/drafts", json={
                "title": "baseline-pending", "due_at": "2026-12-10T16:00:00+08:00"})
            assert pending.status_code == 201
            (root / "expected.json").write_text(json.dumps({
                "task": created.json()["task"], "thread_id": pending.json()["thread_id"],
            }), encoding="utf-8")
        else:
            expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))
            assert api.get("/v1/tasks").json()["items"] == [expected["task"]]
            path = f"/v1/tasks/drafts/{expected['thread_id']}"
            assert api.get(path).json()["status"] == "awaiting_approval"
            completed = api.post(path + "/decision", json={"approved": True})
            assert completed.status_code == 200 and completed.json()["status"] == "created"
            assert api.post(path + "/decision", json={"approved": True}).status_code == 409
            assert api.get("/v1/tasks").json()["count"] == 2
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--out", type=Path, default=Path("reports/r1/compatibility.json"))
    parser.add_argument("--snapshot", choices=["baseline", "current"], help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.snapshot:
        result = snapshot(args.snapshot, args.root)
        (args.root / (args.snapshot + ".json")).write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return 0

    repo = Path(__file__).resolve().parents[1]
    cache = repo / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    if cache.resolve() != cache or not cache.resolve().is_relative_to(repo):
        raise ValueError("unsafe_test_cache")
    root = Path(tempfile.mkdtemp(prefix="r1-compatibility-", dir=cache))
    commit = subprocess.check_output(["git", "rev-parse", args.baseline + "^{commit}"],
                                     cwd=repo, text=True).strip()
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", commit,
                                     "src/productivity_agent"], cwd=repo, text=True).splitlines()
    for name in files:
        target = root / "baseline" / name
        if not target.resolve().is_relative_to(root / "baseline"):
            raise ValueError("unsafe_baseline_path")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Reproduce checkout bytes, including core.autocrlf/package-data line endings.
        target.write_bytes(subprocess.check_output(["git", "cat-file", "--filters", commit + ":" + name],
                                                  cwd=repo))
    env = dict(os.environ, PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="", PPA_AUTH_CONFIG="",
               PPA_API_TOKEN="", PPA_TASK_SERVICE_URL="", PPA_DATA_DIR=str(root / "data"),
               LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    for mode, source in (("baseline", root / "baseline/src"), ("current", repo / "src")):
        env["PYTHONPATH"] = str(source)
        with (root / (mode + ".log")).open("w", encoding="utf-8") as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--snapshot", mode,
                            "--root", str(root)], env=env, cwd=repo, stdout=log, stderr=log,
                           check=True, timeout=90)
    previous = json.loads((root / "baseline.json").read_text(encoding="utf-8"))
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert previous == current, "R1 HTTP/OpenAPI/route-order/SSE/static-page compatibility changed"
    summary = {"status": "PASS", "baseline": commit, "live_qwen_calls": 0, "cost_cny": 0,
               "baseline_database_read": True, "baseline_checkpoint_resumed": True,
               "route_order_identical": True, "calendar_json_and_sse_identical": True,
               "routes": {app: current[app + "_routes"] for app in ("assistant", "business")},
               "duplicate_approval_status": 409, "page_sha256": current["page_sha256"],
               "openapi_sha256": {app: hashlib.sha256(json.dumps(current[app + "_openapi"],
                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                                  for app in ("assistant", "business")}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("R1 baseline compatibility: PASS; existing synthetic database/checkpoint resumed; model calls=0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Immutable R1.1 producer -> candidate consumer; synthetic fixtures only.

Run with Python 3.12 and the recorded dependency set. The fixed Git revision is
never replaced by HEAD. Each producer, consumer and verifier has a fresh process.
The candidate is B0's unchanged implementation until a later authorized slice.
"""
import argparse
import hashlib
import io
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

BASELINE = "40d837c19f42ffd373686c30f4797df2e2598e23"
REPO = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO / "tests/fixtures/r2_b0/contracts.json"
WORKER = REPO / "scripts/r2_baseline_worker.py"


def export_baseline(root):
    archive = subprocess.run(["git", "archive", BASELINE, "src/productivity_agent"],
                             cwd=REPO, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(root, filter="data")
    return root / "src"


def source_manifest(source):
    return {str(path.relative_to(source)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for path in sorted((source / "productivity_agent").rglob("*"))
            if path.is_file() and path.suffix in {".py", ".html"}}


def environment(source):
    return dict(os.environ, PYTHONPATH=str(source), PPA_ENABLE_LIVE_QWEN="0", DASHSCOPE_API_KEY="",
                PPA_API_TOKEN="", PPA_AUTH_CONFIG="", PPA_TASK_SERVICE_URL="",
                LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", PYTHONIOENCODING="utf-8")


def worker(mode, phase, root, source, *, auth=False, url=""):
    env = environment(source)
    env["PPA_DATA_DIR"] = str(root / "contracts-data")
    env["PPA_TASK_SERVICE_URL"] = url
    args = [sys.executable, str(WORKER), mode, phase, str(root)] + (["--auth"] if auth else [])
    with (root / f"{mode}-{phase}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(args, cwd=root, env=env, stdout=log, stderr=log, timeout=300, check=False)
    assert result.returncode == 0, f"{mode}/{phase} failed; inspect {root / f'{mode}-{phase}.log'}"
    data = json.loads((root / f"{mode}-{phase}.json").read_text(encoding="utf-8"))
    assert Path(data["source_root"]) == source / "productivity_agent", data["source_root"]
    return data


def setup_auth(root):
    token = secrets.token_hex(24)
    (root / "credential").write_text(token, encoding="utf-8")
    auth = root / "accounts.json"
    auth.write_text(json.dumps({"users": {
        "b0-owner": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()},
        "b0-other": {"token_sha256": hashlib.sha256((token + "x").encode()).hexdigest()},
    }}), encoding="utf-8")
    return auth


@contextmanager
def business_server(root, source, auth):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    data = root / "business"
    data.mkdir(exist_ok=True)
    env = environment(source)
    env.update(PPA_DATA_DIR=str(data), PPA_AUTH_CONFIG=str(auth) if auth else "")
    with (root / f"business-{port}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn",
            "productivity_agent.api.task_service:create_task_service", "--factory",
            "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
            cwd=root, env=env, stdout=log, stderr=log)
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 30
            while True:
                assert process.poll() is None, "business server stopped"
                try:
                    if httpx.get(url + "/health", timeout=0.3, trust_env=False).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "business startup timed out"
                time.sleep(0.05)
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def audit_business(path):
    with sqlite3.connect(path) as conn:
        tasks = list(conn.execute("SELECT id,version,status,owner_id FROM tasks ORDER BY id"))
        creations = conn.execute("SELECT count(*) FROM task_operations").fetchone()[0]
        changes = conn.execute("SELECT count(*) FROM task_changes").fetchone()[0]
    return {"tasks": tasks, "creations": creations, "changes": changes,
            "version_sum": sum(row[1] for row in tasks)}


def assert_contract_equal(expected, actual, path="$"):
    """Exact JSON structure/value/type equality; report the first changed field."""
    assert type(expected) is type(actual), f"contract changed at {path}: value type"
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys(), f"contract changed at {path}: fields"
        for key in expected:
            assert_contract_equal(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(expected) == len(actual), f"contract changed at {path}: list length"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            assert_contract_equal(left, right, f"{path}[{index}]")
    else:
        assert expected == actual, f"contract changed at {path}: value"


def verify(root, *, refresh_snapshot=False, checkpoints=True, candidate_source=None):
    root.mkdir(parents=True, exist_ok=True)
    old = export_baseline(root / "baseline")
    current = candidate_source if candidate_source is not None else REPO / "src"
    report = {"baseline": BASELINE, "candidate_head": subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip(),
        "baseline_source": source_manifest(old), "candidate_source": source_manifest(current),
        "live_model_calls": 0, "worker_processes": [], "matrix": {}}
    for phase, source in [("produce", old), ("consume", current)]:
        folder = root / ("contracts-" + phase)
        folder.mkdir()
        data = worker("contracts", phase, folder, source)
        report["worker_processes"].append({k: data[k] for k in ["pid", "phase", "source_root"]})
        if phase == "produce":
            frozen = {"baseline": BASELINE, "versions": data["versions"], "contracts": data["result"]}
        else:
            assert_contract_equal(frozen["contracts"], data["result"])
            assert_contract_equal(frozen["versions"], data["versions"], "$.versions")
    if refresh_snapshot:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        assert_contract_equal(json.loads(SNAPSHOT.read_text(encoding="utf-8")), frozen, "$.snapshot")
    report["contracts_exact"] = True
    report["versions"] = frozen["versions"]
    if not checkpoints:
        return report
    for authenticated in [False, True]:
        for remote in [False, True]:
            name = f"{'auth' if authenticated else 'legacy'}-{'http' if remote else 'sqlite'}"
            folder = root / name
            folder.mkdir()
            auth = setup_auth(folder) if authenticated else None
            phases = {}
            audits = {}
            for phase, source in [("produce", old), ("consume", current), ("verify", current)]:
                if remote:
                    with business_server(folder, source, auth) as url:
                        data = worker("web", phase, folder, source, auth=authenticated, url=url)
                else:
                    data = worker("web", phase, folder, source, auth=authenticated)
                phases[phase] = data["result"]
                report["worker_processes"].append({k: data[k] for k in ["pid", "phase", "source_root"]})
                audits[phase] = audit_business(folder / ("business" if remote else "web") / "tasks.sqlite")
            assert audits["consume"] == audits["verify"], "terminal replay duplicated business effects"
            assert audits["consume"]["creations"] == 12
            assert audits["consume"]["changes"] == 2
            assert audits["consume"]["version_sum"] == 14
            # After-commit failures must keep the same durable Task IDs across source/process boundaries.
            produced_ids = {row[0] for row in audits["produce"]["tasks"]}
            assert produced_ids <= {row[0] for row in audits["consume"]["tasks"]}
            crash_ops = {item["before"]["operation_id"] for item in phases["produce"]["outcomes"]
                         if item["scenario"].endswith("after_commit")}
            for op in crash_ops:
                first = [c for c in phases["produce"]["calls"] if c["operation_id"] == op]
                second = [c for c in phases["consume"]["calls"] if c["operation_id"] == op]
                assert len(first) == len(second) == 1, (op, first, second)
                assert first[0]["thread_id"] == second[0]["thread_id"]
                assert first[0]["checkpoint_ns"].split("|")[0] == second[0]["checkpoint_ns"].split("|")[0]
                assert second[0]["inherited_checkpointer"] == "AsyncSqliteSaver"
            assert not phases["verify"]["calls"], "terminal HTTP replays must not write"
            assert phases["produce"]["child_checkpoints"], "nested saver state was not inspected"
            report["matrix"][name] = {"phases": phases, "durable_audits": audits}
    folder = root / "m5-sync"
    folder.mkdir()
    phases = {}
    for phase, source in [("produce", old), ("consume", current), ("verify", current)]:
        data = worker("sync", phase, folder, source)
        phases[phase] = data["result"]
        report["worker_processes"].append({k: data[k] for k in ["pid", "phase", "source_root"]})
    assert not phases["verify"]["calls"]
    first = [c for c in phases["produce"]["calls"] if c["operation_id"] == "op-after_commit"]
    second = [c for c in phases["consume"]["calls"] if c["operation_id"] == "op-after_commit"]
    assert len(first) == len(second) == 1
    assert first[0]["checkpoint_ns"].split("|")[0] == second[0]["checkpoint_ns"].split("|")[0]
    assert second[0]["inherited_checkpointer"] == "SqliteSaver"
    assert second[0]["recursion_limit"] == 23
    report["matrix"]["m5-sync"] = phases
    report["implementation_changed"] = report["baseline_source"] != report["candidate_source"]
    report["scope"] = ("fixed baseline producer -> candidate source consumer, then fresh-process verifier; "
                       "B0 production code is unchanged. Future migrated code must rerun this gate.")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("reports/r2-b0/compatibility.json"))
    parser.add_argument("--refresh-snapshot", action="store_true",
                        help="B0 initial freeze only; always derives from the fixed baseline, never the candidate")
    parser.add_argument("--contracts-only", action="store_true")
    args = parser.parse_args()
    cache = REPO / ".pytest_cache/r2-b0"
    cache.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="run-", dir=cache))
    report = verify(root, refresh_snapshot=args.refresh_snapshot, checkpoints=not args.contracts_only)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "baseline": BASELINE, "matrix": list(report["matrix"]),
                      "runtime_evidence": str(root), "report": str(args.out), "live_model_calls": 0}))


if __name__ == "__main__":
    main()

"""M7 reproducible offline acceptance suite for deterministic business rules.

This is *not* a live-LLM benchmark. Zero model calls and zero model fees.
For the real LangGraph/HTTP integration tests, run `python -m pytest -q`.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

from productivity_agent.domain.calendar_rules import assess_calendar
from productivity_agent.services.task_store import (
    AmbiguousCommitError,
    IdempotencyConflict,
    SQLiteTaskStore,
    TransientWriteError,
)

BASE_START = "2026-12-10T15:00:00+08:00"
BASE_END = "2026-12-10T16:00:00+08:00"


def req(start=BASE_START, end=BASE_END, title="组会") -> dict:
    return {"title": title, "start_at": start, "end_at": end}


def slot(start, end) -> dict:
    return {"start_at": start, "end_at": end}


def _calendar_available() -> None:
    assert assess_calendar(req(), [])["status"] == "available"


def _calendar_conflict() -> None:
    outcome = assess_calendar(req(), [slot("2026-12-10T15:30:00+08:00", "2026-12-10T16:30:00+08:00")])
    assert outcome["status"] == "conflict"
    assert outcome["suggested_start"] == "2026-12-10T16:30:00+08:00"


def _calendar_boundary() -> None:
    assert assess_calendar(req(), [slot("2026-12-10T16:00:00+08:00", "2026-12-10T17:00:00+08:00")])["status"] == "available"


def _calendar_invalid() -> None:
    assert assess_calendar(req(end="2026-12-10T14:00:00+08:00"), [])["status"] == "invalid"
    assert assess_calendar(req(start="2026-12-10T15:00:00"), [])["status"] == "invalid"


def _calendar_no_slot() -> None:
    blocked = [slot("2026-12-10T15:00:00+08:00", "2026-12-10T18:00:00+08:00")]
    assert assess_calendar(req(), blocked)["status"] == "no_available_slot"


def _store_replay() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteTaskStore(Path(directory) / "tasks.sqlite")
        first = store.create_task("op-replay", "准备组会", BASE_START)
        replay = store.create_task("op-replay", "准备组会", BASE_START)
        assert first["status"] == "created"
        assert replay["status"] == "replayed"
        assert replay["task"]["id"] == first["task"]["id"]
        assert store.count_tasks() == 1


def _ambiguous_commit_reconcile() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteTaskStore(Path(directory) / "tasks.sqlite")
        try:
            store.create_task("op-timeout", "准备组会", BASE_START, fault="after_commit")
        except AmbiguousCommitError:
            pass
        else:
            raise AssertionError("expected injected after-commit timeout")
        task = store.lookup("op-timeout", "准备组会", BASE_START)
        assert task is not None
        assert store.create_task("op-timeout", "准备组会", BASE_START)["status"] == "replayed"
        assert store.count_tasks() == 1


def _before_commit_retry() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteTaskStore(Path(directory) / "tasks.sqlite")
        try:
            store.create_task("op-transient", "准备组会", BASE_START, fault="before_commit")
        except TransientWriteError:
            pass
        else:
            raise AssertionError("expected injected before-commit error")
        assert store.count_tasks() == 0
        assert store.create_task("op-transient", "准备组会", BASE_START)["status"] == "created"
        assert store.count_tasks() == 1


def _idempotency_key_conflict() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteTaskStore(Path(directory) / "tasks.sqlite")
        store.create_task("op-collision", "准备组会", BASE_START)
        try:
            store.create_task("op-collision", "不同任务", BASE_START)
        except IdempotencyConflict:
            pass
        else:
            raise AssertionError("reusing operation ID with changed parameters must be rejected")
        assert store.count_tasks() == 1


def _concurrent_replay() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory) / "tasks.sqlite"
        store = SQLiteTaskStore(db)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: store.create_task("op-parallel", "准备组会", BASE_START), range(6)))
        assert store.count_tasks() == 1
        assert len({r["task"]["id"] for r in results}) == 1
        assert [r["status"] for r in results].count("created") == 1


CASES: dict[str, Callable[[], None]] = {
    "calendar_available": _calendar_available,
    "calendar_conflict_replanning": _calendar_conflict,
    "calendar_half_open_boundary": _calendar_boundary,
    "calendar_reject_invalid": _calendar_invalid,
    "calendar_no_available_slot": _calendar_no_slot,
    "task_idempotent_replay": _store_replay,
    "task_after_commit_timeout_reconciliation": _ambiguous_commit_reconcile,
    "task_before_commit_retry": _before_commit_retry,
    "task_idempotency_conflict": _idempotency_key_conflict,
    "task_concurrent_duplicate_requests": _concurrent_replay,
}


def run_evaluation() -> dict:
    records = []
    for name, test in CASES.items():
        started = perf_counter()
        error = None
        try:
            test()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        duration_ms = round((perf_counter() - started) * 1000, 3)
        records.append({"case": name, "passed": error is None, "latency_ms": duration_ms, "error": error})
    passed = sum(int(row["passed"]) for row in records)
    latency = [row["latency_ms"] for row in records]
    return {
        "suite": "M7-deterministic-offline-acceptance",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "os": platform.system()},
        "total": len(records), "passed": passed, "failed": len(records) - passed,
        "pass_rate": round(passed / len(records), 4),
        "latency_ms": {"mean": round(statistics.mean(latency), 3), "max": max(latency)},
        "llm_calls": 0, "llm_cost_cny": 0,
        "limitations": "Synthetic fixed cases and local SQLite only; not a live Qwen or production latency benchmark. Framework/API integration is tested separately by pytest.",
        "cases": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M7 deterministic, zero-LLM acceptance suite")
    parser.add_argument("--out", default="reports/m7-offline-evaluation.json")
    args = parser.parse_args()
    report = run_evaluation()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"M7 offline acceptance: {report['passed']}/{report['total']} passed; report: {path}")
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
